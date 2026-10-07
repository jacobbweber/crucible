"""Background tick loop, cron evaluation, and catch-up engine for agent-os."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_os.domain.schedule import RoutineExecutionLog, ScheduledRoutine
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.infrastructure.storage.routine_repo import RoutineRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher


def _match_cron_field(val: int, expr: str, is_dow: bool = False) -> bool:
    """Evaluate whether a numeric datetime field matches a cron field expression."""
    if expr == "*":
        return True
    if expr.startswith("*/"):
        try:
            step = int(expr[2:])
            return val % step == 0
        except ValueError:
            return False
    if "," in expr:
        return any(_match_cron_field(val, p.strip(), is_dow) for p in expr.split(","))
    if "-" in expr:
        parts = expr.split("-")
        if len(parts) == 2:
            try:
                start, end = int(parts[0]), int(parts[1])
                return start <= val <= end
            except ValueError:
                return False
    try:
        target = int(expr)
        if is_dow and target == 7 and val == 0:
            return True
        return val == target
    except ValueError:
        return False


def compute_next_run(cron_expression: str, from_time: datetime) -> datetime:
    """Compute the next scheduled execution datetime from cron or interval specification."""
    expr = cron_expression.strip().lower()

    if expr.startswith("@interval"):
        parts = expr.split()
        seconds = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 3600
        return from_time + timedelta(seconds=seconds)

    if expr == "@hourly":
        return from_time + timedelta(hours=1)
    if expr == "@daily":
        return from_time + timedelta(days=1)
    if expr == "@weekly":
        return from_time + timedelta(days=7)

    parts = expr.split()
    if len(parts) == 5:
        curr = from_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(527040):
            dow = (curr.weekday() + 1) % 7
            if (
                _match_cron_field(curr.minute, parts[0])
                and _match_cron_field(curr.hour, parts[1])
                and _match_cron_field(curr.day, parts[2])
                and _match_cron_field(curr.month, parts[3])
                and _match_cron_field(dow, parts[4], is_dow=True)
            ):
                return curr
            curr += timedelta(minutes=1)

    return from_time + timedelta(hours=1)


class EmbeddedSchedulerDaemon:
    """Background scheduler daemon managing recurring routines and hardware concurrency."""

    def __init__(
        self,
        dispatcher: ZeroCatalogDispatcher,
        semaphore: InferenceSemaphore,
        routines: list[ScheduledRoutine] | None = None,
        routine_repo: RoutineRepository | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.semaphore = semaphore
        self.routine_repo = routine_repo
        self.routines: dict[str, ScheduledRoutine] = {}
        self._missed_routines: list[ScheduledRoutine] = []

        if self.routine_repo is not None:
            for r in self.routine_repo.list_routines():
                self.routines[r.routine_id] = r
        if routines:
            for r in routines:
                self.routines[r.routine_id] = r

    def register_routine(self, routine: ScheduledRoutine) -> None:
        """Register a new or updated scheduled routine."""
        self.routines[routine.routine_id] = routine
        if self.routine_repo is not None:
            self.routine_repo.upsert_routine(routine)

    def delete_routine(self, routine_id: str) -> bool:
        """Unregister and remove a routine by ID."""
        removed = self.routines.pop(routine_id, None) is not None
        if self.routine_repo is not None:
            self.routine_repo.delete_routine(routine_id)
        return removed

    def get_routine(self, routine_id: str) -> ScheduledRoutine | None:
        """Retrieve a registered routine by ID."""
        return self.routines.get(routine_id)

    def list_routines(self) -> list[ScheduledRoutine]:
        """Return all registered scheduled routines."""
        return list(self.routines.values())

    @staticmethod
    def compute_next_run(cron_expression: str, from_time: datetime) -> datetime:
        """Compute the next scheduled execution timestamp."""
        return compute_next_run(cron_expression, from_time)

    def _is_concurrency_saturated(self) -> bool:
        """Check whether the inference semaphore is currently saturated without blocking."""
        sem_any: Any = self.semaphore
        sub_sem: Any = getattr(sem_any, "_semaphore", None)
        if sub_sem is not None and hasattr(sub_sem, "locked") and callable(sub_sem.locked):
            if sub_sem.locked():
                return True

        active = getattr(sem_any, "active_workers", None)
        max_conc = getattr(sem_any, "max_concurrency", None)
        if isinstance(active, int) and isinstance(max_conc, int):
            if active >= max_conc:
                return True

        if hasattr(sem_any, "locked") and callable(sem_any.locked):
            if sem_any.locked():
                return True

        return False

    def get_missed_routines(self) -> list[ScheduledRoutine]:
        """Return list of missed routines awaiting user on-demand review."""
        return list(self._missed_routines)

    def clear_missed_routines(self) -> None:
        """Clear acknowledged missed routines."""
        self._missed_routines.clear()

    def evaluate_catch_up(self, now: datetime) -> list[ScheduledRoutine]:
        """Identify overdue routines and apply configured catch-up policies."""
        catch_up_routines: list[ScheduledRoutine] = []
        for routine in self.routines.values():
            if not routine.is_active:
                continue

            effective_next = routine.next_run_at
            if effective_next is None and routine.last_run_at is not None:
                effective_next = compute_next_run(routine.cron_expression, routine.last_run_at)

            if effective_next is not None and effective_next < now:
                if routine.catch_up_policy in ("respectful", "notify_and_skip"):
                    routine.next_run_at = compute_next_run(routine.cron_expression, now)
                    self._missed_routines.append(routine)
                elif routine.catch_up_policy == "run_once_immediately":
                    routine.next_run_at = compute_next_run(routine.cron_expression, now)
                    catch_up_routines.append(routine)
                elif routine.catch_up_policy == "skip_to_next":
                    routine.next_run_at = compute_next_run(routine.cron_expression, now)
                elif routine.catch_up_policy == "queue_all":
                    routine.next_run_at = compute_next_run(routine.cron_expression, now)
                    catch_up_routines.append(routine)
                if self.routine_repo is not None:
                    self.routine_repo.upsert_routine(routine)

        return catch_up_routines

    async def tick(self, now: datetime) -> list[RoutineExecutionLog]:
        """Execute due routines per schedule, catch-up policies, and concurrency boundaries."""
        logs: list[RoutineExecutionLog] = []

        # 1. Catch-up evaluation for overdue routines (H6)
        catch_up_routines = self.evaluate_catch_up(now)
        due_dict = {r.routine_id: r for r in catch_up_routines}

        # 2. Check for active routines scheduled for current tick
        for r in self.routines.values():
            if r.is_active and r.next_run_at is not None and r.next_run_at <= now:
                due_dict[r.routine_id] = r

        due_routines = list(due_dict.values())
        if not due_routines:
            return logs

        for r in due_routines:
            # Concurrency Gating (ADR-002)
            if self._is_concurrency_saturated():
                log_entry = RoutineExecutionLog(
                    execution_id=f"exec_{uuid.uuid4().hex[:12]}",
                    routine_id=r.routine_id,
                    started_at=now,
                    completed_at=now,
                    status="skipped_concurrency",
                    error_message="Inference slots saturated",
                )
                logs.append(log_entry)
                if self.routine_repo is not None:
                    self.routine_repo.log_execution(log_entry)
                continue

            exec_id = f"exec_{uuid.uuid4().hex[:12]}"
            started_at = datetime.now(UTC)
            try:
                async with self.semaphore.acquire():
                    await self.dispatcher.dispatch_task(
                        session_id="system_scheduler",
                        task=r.task_payload,
                    )
                r.last_run_at = now
                r.next_run_at = compute_next_run(r.cron_expression, now)
                if self.routine_repo is not None:
                    self.routine_repo.upsert_routine(r)
                log_entry = RoutineExecutionLog(
                    execution_id=exec_id,
                    routine_id=r.routine_id,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    status="success",
                )
                logs.append(log_entry)
                if self.routine_repo is not None:
                    self.routine_repo.log_execution(log_entry)
            except Exception as e:
                log_entry = RoutineExecutionLog(
                    execution_id=exec_id,
                    routine_id=r.routine_id,
                    started_at=started_at,
                    completed_at=datetime.now(UTC),
                    status="failed",
                    error_message=str(e),
                )
                logs.append(log_entry)
                if self.routine_repo is not None:
                    self.routine_repo.log_execution(log_entry)

        return logs
