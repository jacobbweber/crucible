"""Unit tests for EmbeddedSchedulerDaemon background tick loop, cron, and catch-up."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_os.domain.dispatch import DispatchDecision, DispatchResult
from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.schedule import ScheduledRoutine
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.scheduler import EmbeddedSchedulerDaemon


def _create_mock_dispatcher() -> tuple[ZeroCatalogDispatcher, list[tuple[str, str]]]:
    """Create a mock ZeroCatalogDispatcher that records dispatch calls."""
    dispatched_calls: list[tuple[str, str]] = []
    mock_dispatcher = MagicMock(spec=ZeroCatalogDispatcher)

    async def mock_dispatch(
        session_id: str,
        task: str,
        available_tools: list[str] | None = None,
    ) -> DispatchResult:
        dispatched_calls.append((session_id, task))
        decision = DispatchDecision(task=task, stage="matched_recipe")
        envelope = SubJobReturnEnvelope(
            journey_id="j_mock_1",
            status="completed",
            summary="Routine executed successfully",
            token_estimate=50,
        )
        return DispatchResult(decision=decision, envelope=envelope)

    mock_dispatcher.dispatch_task = AsyncMock(side_effect=mock_dispatch)
    return cast(ZeroCatalogDispatcher, mock_dispatcher), dispatched_calls


class MockSaturatedSemaphore:
    """Mock semaphore representing fully saturated hardware inference slots."""

    def __init__(self) -> None:
        self.active_workers = 2
        self.max_concurrency = 2
        self._semaphore = MagicMock()
        self._semaphore.locked.return_value = True

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[None]:
        yield


@pytest.mark.asyncio
async def test_scheduler_register_and_due_detection() -> None:
    """Register routine with next_run_at in past; run tick(); verify execution."""
    dispatcher, dispatched = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    past_due = now - timedelta(minutes=10)

    routine = ScheduledRoutine(
        routine_id="daily_cleanup",
        name="Daily Cleanup Routine",
        cron_expression="@interval 3600",
        task_payload="Perform routine file cleanup",
        next_run_at=past_due,
    )
    scheduler.register_routine(routine)

    logs = await scheduler.tick(now)

    assert len(logs) == 1
    assert logs[0].routine_id == "daily_cleanup"
    assert logs[0].status == "success"
    assert len(dispatched) == 1
    assert dispatched[0] == ("system_scheduler", "Perform routine file cleanup")

    assert routine.last_run_at == now
    assert routine.next_run_at is not None
    assert routine.next_run_at > now


def test_scheduler_catch_up_run_once_immediately() -> None:
    """Seed routine with last_run_at 48h ago; evaluate catch-up; verify single execution."""
    dispatcher, _ = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    last_run = now - timedelta(hours=48)
    scheduled_next = now - timedelta(hours=24)

    routine = ScheduledRoutine(
        routine_id="backup_routine",
        name="Daily Backup",
        cron_expression="@interval 86400",
        task_payload="Run database backup",
        catch_up_policy="run_once_immediately",
        last_run_at=last_run,
        next_run_at=scheduled_next,
    )
    scheduler.register_routine(routine)

    catch_up_routines = scheduler.evaluate_catch_up(now)

    assert len(catch_up_routines) == 1
    assert catch_up_routines[0].routine_id == "backup_routine"
    assert routine.next_run_at is not None
    assert routine.next_run_at > now


def test_scheduler_catch_up_skip_to_next() -> None:
    """Seed routine with policy skip_to_next missed by 2 days; verify 0 executions."""
    dispatcher, _ = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    last_run = now - timedelta(days=2)
    scheduled_next = now - timedelta(days=1)

    routine = ScheduledRoutine(
        routine_id="report_generator",
        name="Daily Report",
        cron_expression="@interval 86400",
        task_payload="Generate executive report",
        catch_up_policy="skip_to_next",
        last_run_at=last_run,
        next_run_at=scheduled_next,
    )
    scheduler.register_routine(routine)

    catch_up_routines = scheduler.evaluate_catch_up(now)

    assert len(catch_up_routines) == 0
    assert routine.next_run_at is not None
    assert routine.next_run_at > now


@pytest.mark.asyncio
async def test_scheduler_hardware_semaphore_gating() -> None:
    """Mock InferenceSemaphore as saturated; run tick(); verify skipped_concurrency."""
    dispatcher, dispatched = _create_mock_dispatcher()
    mock_semaphore = cast(InferenceSemaphore, MockSaturatedSemaphore())
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=mock_semaphore)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    routine = ScheduledRoutine(
        routine_id="heavy_gpu_routine",
        name="Fine-tuning Job",
        cron_expression="@interval 3600",
        task_payload="Run GPU training step",
        next_run_at=now - timedelta(minutes=5),
    )
    scheduler.register_routine(routine)

    logs = await scheduler.tick(now)

    assert len(logs) == 1
    assert logs[0].routine_id == "heavy_gpu_routine"
    assert logs[0].status == "skipped_concurrency"
    assert logs[0].error_message == "Inference slots saturated"
    assert len(dispatched) == 0
    assert routine.last_run_at is None


@pytest.mark.asyncio
async def test_scheduler_persistence_across_restarts(tmp_path: Path) -> None:
    """Verify routines and execution logs persist across scheduler daemon restarts (H6)."""
    db_file = tmp_path / "session_store.db"
    from agent_os.infrastructure.storage.routine_repo import RoutineRepository

    repo = RoutineRepository(db_file)
    dispatcher, dispatched = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)

    # Instance 1: Register and run routine
    scheduler1 = EmbeddedSchedulerDaemon(
        dispatcher=dispatcher, semaphore=semaphore, routine_repo=repo
    )
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    routine = ScheduledRoutine(
        routine_id="periodic_summary",
        name="Periodic Summary",
        cron_expression="@interval 3600",
        task_payload="Generate periodic system summary",
        next_run_at=now,
    )
    scheduler1.register_routine(routine)

    logs1 = await scheduler1.tick(now)
    assert len(logs1) == 1
    assert logs1[0].status == "success"
    assert len(dispatched) == 1

    # Instance 2 (Simulating Process Restart): Re-initialize with same repository
    dispatcher2, dispatched2 = _create_mock_dispatcher()
    scheduler2 = EmbeddedSchedulerDaemon(
        dispatcher=dispatcher2, semaphore=semaphore, routine_repo=repo
    )

    restored_routines = scheduler2.list_routines()
    assert len(restored_routines) == 1
    restored = restored_routines[0]
    assert restored.routine_id == "periodic_summary"
    assert restored.last_run_at == now
    assert restored.next_run_at is not None and restored.next_run_at > now

    # Verify execution audit log was persisted to repository
    saved_logs = repo.list_execution_logs(routine_id="periodic_summary")
    assert len(saved_logs) == 1
    assert saved_logs[0].status == "success"


@pytest.mark.asyncio
async def test_scheduler_tick_catch_up_skip_to_next() -> None:
    """Overdue routine with skip_to_next policy advances next_run_at without executing."""
    dispatcher, dispatched = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    overdue_time = now - timedelta(hours=5)

    routine = ScheduledRoutine(
        routine_id="missed_routine",
        name="Missed Task",
        cron_expression="@interval 3600",
        task_payload="perform missed task",
        catch_up_policy="skip_to_next",
        next_run_at=overdue_time,
    )
    scheduler.register_routine(routine)

    logs = await scheduler.tick(now)

    assert len(logs) == 0
    assert len(dispatched) == 0
    assert routine.next_run_at is not None
    assert routine.next_run_at > now
    assert routine.last_run_at is None


@pytest.mark.asyncio
async def test_scheduler_tick_catch_up_run_once_immediately() -> None:
    """Overdue routine with run_once_immediately policy executes once during tick."""
    dispatcher, dispatched = _create_mock_dispatcher()
    semaphore = InferenceSemaphore(max_concurrency=2)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    overdue_time = now - timedelta(hours=3)

    routine = ScheduledRoutine(
        routine_id="catch_up_once",
        name="Catch Up Task",
        cron_expression="@interval 3600",
        task_payload="perform catch up task",
        catch_up_policy="run_once_immediately",
        next_run_at=overdue_time,
    )
    scheduler.register_routine(routine)

    logs = await scheduler.tick(now)

    assert len(logs) == 1
    assert logs[0].status == "success"
    assert len(dispatched) == 1
    assert dispatched[0] == ("system_scheduler", "perform catch up task")
    assert routine.last_run_at == now
    assert routine.next_run_at is not None
    assert routine.next_run_at > now
