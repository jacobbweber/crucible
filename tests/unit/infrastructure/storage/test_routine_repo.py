"""Unit tests for RoutineRepository persistent storage and execution logging."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_os.domain.schedule import RoutineExecutionLog, ScheduledRoutine
from agent_os.infrastructure.storage.routine_repo import RoutineRepository


def test_routine_repo_upsert_and_retrieve(tmp_path: Path) -> None:
    """Upsert routine; retrieve by id and verify fields; update and re-verify."""
    repo = RoutineRepository(tmp_path / "session_store.db")
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    routine = ScheduledRoutine(
        routine_id="routine_backup_001",
        name="Nightly Backup",
        cron_expression="@daily",
        task_payload="backup all sqlite databases",
        catch_up_policy="run_once_immediately",
        is_active=True,
        last_run_at=now - timedelta(days=1),
        next_run_at=now,
    )

    repo.upsert_routine(routine)
    fetched = repo.get_routine("routine_backup_001")

    assert fetched is not None
    assert fetched.routine_id == "routine_backup_001"
    assert fetched.name == "Nightly Backup"
    assert fetched.cron_expression == "@daily"
    assert fetched.task_payload == "backup all sqlite databases"
    assert fetched.catch_up_policy == "run_once_immediately"
    assert fetched.is_active is True
    assert fetched.last_run_at == now - timedelta(days=1)
    assert fetched.next_run_at == now

    # Update routine
    routine.is_active = False
    routine.task_payload = "updated backup payload"
    repo.upsert_routine(routine)

    updated = repo.get_routine("routine_backup_001")
    assert updated is not None
    assert updated.is_active is False
    assert updated.task_payload == "updated backup payload"


def test_routine_repo_list_and_delete(tmp_path: Path) -> None:
    """Insert multiple routines; verify list ordering; delete one and verify removal."""
    repo = RoutineRepository(tmp_path / "session_store.db")

    r1 = ScheduledRoutine(
        routine_id="routine_alpha",
        name="Alpha Routine",
        cron_expression="@hourly",
        task_payload="run alpha",
    )
    r2 = ScheduledRoutine(
        routine_id="routine_beta",
        name="Beta Routine",
        cron_expression="@hourly",
        task_payload="run beta",
    )

    repo.upsert_routine(r2)
    repo.upsert_routine(r1)

    routines = repo.list_routines()
    assert len(routines) == 2
    assert routines[0].routine_id == "routine_alpha"
    assert routines[1].routine_id == "routine_beta"

    deleted = repo.delete_routine("routine_alpha")
    assert deleted is True
    assert repo.get_routine("routine_alpha") is None
    assert len(repo.list_routines()) == 1


def test_routine_repo_persistence_across_instances(tmp_path: Path) -> None:
    """Verify data persists when a new RoutineRepository opens the same database."""
    db_file = tmp_path / "session_store.db"
    repo1 = RoutineRepository(db_file)

    r = ScheduledRoutine(
        routine_id="routine_persist",
        name="Persistent Routine",
        cron_expression="*/15 * * * *",
        task_payload="persist task",
    )
    repo1.upsert_routine(r)

    # Reopen from new instance
    repo2 = RoutineRepository(db_file)
    restored = repo2.get_routine("routine_persist")
    assert restored is not None
    assert restored.name == "Persistent Routine"
    assert restored.cron_expression == "*/15 * * * *"


def test_routine_repo_execution_logs(tmp_path: Path) -> None:
    """Record execution logs; verify listing and filtering by routine_id."""
    repo = RoutineRepository(tmp_path / "session_store.db")
    now = datetime.now(UTC)

    log1 = RoutineExecutionLog(
        execution_id="exec_1",
        routine_id="routine_x",
        started_at=now - timedelta(minutes=5),
        completed_at=now - timedelta(minutes=4),
        status="success",
    )
    log2 = RoutineExecutionLog(
        execution_id="exec_2",
        routine_id="routine_x",
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        status="failed",
        error_message="Disk full",
    )
    log3 = RoutineExecutionLog(
        execution_id="exec_3",
        routine_id="routine_y",
        started_at=now,
        completed_at=now,
        status="skipped_concurrency",
        error_message="Inference slots saturated",
    )

    repo.log_execution(log1)
    repo.log_execution(log2)
    repo.log_execution(log3)

    # All logs
    all_logs = repo.list_execution_logs()
    assert len(all_logs) == 3
    assert all_logs[0].execution_id == "exec_3"  # Most recent first

    # Filtered by routine_id
    x_logs = repo.list_execution_logs(routine_id="routine_x")
    assert len(x_logs) == 2
    assert x_logs[0].execution_id == "exec_2"
    assert x_logs[1].execution_id == "exec_1"
    assert x_logs[0].status == "failed"
    assert x_logs[0].error_message == "Disk full"
