"""SQLite storage repository for scheduled routines and execution audit logs."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

from agent_os.domain.schedule import CatchUpPolicy, RoutineExecutionLog, ScheduledRoutine

ROUTINE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scheduled_routines (
    routine_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    task_payload TEXT NOT NULL,
    catch_up_policy TEXT NOT NULL DEFAULT 'run_once_immediately',
    is_active INTEGER NOT NULL DEFAULT 1,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS routine_execution_logs (
    execution_id TEXT PRIMARY KEY,
    routine_id TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    status TEXT NOT NULL,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_routine_logs_routine_id ON routine_execution_logs(routine_id);
"""


@contextmanager
def get_routine_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open, configure with WAL, and automatically close an SQLite routine connection."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_routine_db(db_path: Path) -> None:
    """Initialize SQLite database tables for scheduled routines."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_routine_connection(db_path) as conn:
        conn.executescript(ROUTINE_SCHEMA_SQL)


class RoutineRepository:
    """Repository for managing persistent scheduled routines and execution logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_routine_db(self.db_path)

    @staticmethod
    def _row_to_routine(row: sqlite3.Row) -> ScheduledRoutine:
        last_run = datetime.fromisoformat(row["last_run_at"]) if row["last_run_at"] else None
        next_run = datetime.fromisoformat(row["next_run_at"]) if row["next_run_at"] else None
        return ScheduledRoutine(
            routine_id=row["routine_id"],
            name=row["name"],
            cron_expression=row["cron_expression"],
            task_payload=row["task_payload"],
            catch_up_policy=cast(CatchUpPolicy, row["catch_up_policy"]),
            is_active=bool(row["is_active"]),
            last_run_at=last_run,
            next_run_at=next_run,
        )

    def upsert_routine(self, routine: ScheduledRoutine) -> ScheduledRoutine:
        """Insert or update a scheduled routine record."""
        last_run_str = routine.last_run_at.isoformat() if routine.last_run_at else None
        next_run_str = routine.next_run_at.isoformat() if routine.next_run_at else None
        with get_routine_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_routines (
                    routine_id, name, cron_expression, task_payload,
                    catch_up_policy, is_active, last_run_at, next_run_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(routine_id) DO UPDATE SET
                    name = excluded.name,
                    cron_expression = excluded.cron_expression,
                    task_payload = excluded.task_payload,
                    catch_up_policy = excluded.catch_up_policy,
                    is_active = excluded.is_active,
                    last_run_at = excluded.last_run_at,
                    next_run_at = excluded.next_run_at;
                """,
                (
                    routine.routine_id,
                    routine.name,
                    routine.cron_expression,
                    routine.task_payload,
                    routine.catch_up_policy,
                    1 if routine.is_active else 0,
                    last_run_str,
                    next_run_str,
                ),
            )
        return routine

    def get_routine(self, routine_id: str) -> ScheduledRoutine | None:
        """Fetch a single routine by routine_id or return None."""
        with get_routine_connection(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM scheduled_routines WHERE routine_id = ?;",
                (routine_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_routine(row)

    def list_routines(self) -> list[ScheduledRoutine]:
        """Fetch all stored routines ordered by routine_id."""
        with get_routine_connection(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM scheduled_routines ORDER BY routine_id ASC;")
            rows = cursor.fetchall()
        return [self._row_to_routine(row) for row in rows]

    def delete_routine(self, routine_id: str) -> bool:
        """Delete a routine record and its associated execution logs."""
        with get_routine_connection(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM scheduled_routines WHERE routine_id = ?;",
                (routine_id,),
            )
            return cursor.rowcount > 0

    def log_execution(self, log: RoutineExecutionLog) -> RoutineExecutionLog:
        """Record an execution outcome in the audit table."""
        completed_str = log.completed_at.isoformat() if log.completed_at else None
        with get_routine_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO routine_execution_logs (
                    execution_id, routine_id, started_at, completed_at, status, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    log.execution_id,
                    log.routine_id,
                    log.started_at.isoformat(),
                    completed_str,
                    log.status,
                    log.error_message,
                ),
            )
        return log

    def list_execution_logs(
        self, routine_id: str | None = None, limit: int = 50
    ) -> list[RoutineExecutionLog]:
        """List execution audit logs optionally filtered by routine_id."""
        with get_routine_connection(self.db_path) as conn:
            if routine_id:
                cursor = conn.execute(
                    """
                    SELECT execution_id, routine_id, started_at, completed_at, status, error_message
                    FROM routine_execution_logs
                    WHERE routine_id = ?
                    ORDER BY started_at DESC
                    LIMIT ?;
                    """,
                    (routine_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT execution_id, routine_id, started_at, completed_at, status, error_message
                    FROM routine_execution_logs
                    ORDER BY started_at DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()

        logs: list[RoutineExecutionLog] = []
        for r in rows:
            completed = datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None
            logs.append(
                RoutineExecutionLog(
                    execution_id=r["execution_id"],
                    routine_id=r["routine_id"],
                    started_at=datetime.fromisoformat(r["started_at"]),
                    completed_at=completed,
                    status=r["status"],
                    error_message=r["error_message"],
                )
            )
        return logs
