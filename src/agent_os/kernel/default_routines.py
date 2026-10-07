"""Default routine provisioning for scheduled background maintenance."""

from datetime import UTC, datetime, timedelta

from agent_os.domain.schedule import ScheduledRoutine
from agent_os.infrastructure.storage.routine_repo import RoutineRepository


def ensure_default_routines(routine_repo: RoutineRepository) -> None:
    """Idempotently register core background maintenance routines."""
    if not routine_repo.get_routine("routine_weekly_telemetry_prune"):
        routine_repo.upsert_routine(
            ScheduledRoutine(
                routine_id="routine_weekly_telemetry_prune",
                name="Weekly Telemetry Prune",
                cron_expression="0 3 * * 0",
                task_payload="telemetry_prune_old_records",
                catch_up_policy="skip_to_next",
                next_run_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
