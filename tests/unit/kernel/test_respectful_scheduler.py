"""Unit tests for respectful scheduling policy and missed routine notifications."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from agent_os.domain.schedule import ScheduledRoutine
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.scheduler import EmbeddedSchedulerDaemon


def test_respectful_catchup_skips_immediate_run_and_tracks_missed() -> None:
    """Verify overdue routine with 'respectful' policy tracks missed without immediate queue."""
    dispatcher = MagicMock(spec=ZeroCatalogDispatcher)
    semaphore = MagicMock(spec=InferenceSemaphore)
    scheduler = EmbeddedSchedulerDaemon(dispatcher=dispatcher, semaphore=semaphore)

    now = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
    overdue_time = now - timedelta(hours=3)

    routine = ScheduledRoutine(
        routine_id="rt_lint",
        name="Warehouse Health Lint",
        cron_expression="@hourly",
        task_payload="Run warehouse lint",
        catch_up_policy="respectful",
        last_run_at=overdue_time,
        next_run_at=overdue_time + timedelta(hours=1),
    )
    scheduler.register_routine(routine)

    # Evaluate catchup on boot/wake
    catch_up_to_run = scheduler.evaluate_catch_up(now)

    # Should NOT be queued for immediate execution
    assert len(catch_up_to_run) == 0

    # Next run should be scheduled forward to next interval
    assert routine.next_run_at is not None
    assert routine.next_run_at > now

    # Missed routine is tracked for ambient user notification
    missed = scheduler.get_missed_routines()
    assert len(missed) == 1
    assert missed[0].routine_id == "rt_lint"

    # Clearing resets the notification queue
    scheduler.clear_missed_routines()
    assert len(scheduler.get_missed_routines()) == 0
