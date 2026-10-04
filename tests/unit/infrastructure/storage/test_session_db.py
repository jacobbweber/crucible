"""Unit tests for SQLite session database initialization and constraints."""

import sqlite3
from pathlib import Path

import pytest

from agent_os.infrastructure.storage.session_db import get_connection, init_db


def test_init_db_creates_tables_and_indices(tmp_path: Path) -> None:
    """Verify schema initialization creates all 4 tables and their indices."""
    db_file = tmp_path / "test_session_store.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        assert {"sessions", "turns", "journeys", "journey_steps"}.issubset(tables)

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
        }
        assert "idx_turns_session_turn" in indices
        assert "idx_journeys_session" in indices
        assert "idx_journey_steps_journey_step" in indices


def test_foreign_key_cascade_delete(tmp_path: Path) -> None:
    """Verify deleting a session cascades to its turns and journeys."""
    db_file = tmp_path / "test_session_store.db"
    init_db(db_file)

    with get_connection(db_file) as conn:
        # Foreign key integrity check
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, turn_index, role, content, token_count, created_at
                )
                VALUES ('t1', 'nonexistent_session', 0, 'user', 'hello', 5, '2026-10-04T00:00:00Z');
                """
            )

        # Insert valid session and child records
        conn.execute(
            """
            INSERT INTO sessions (session_id, title, created_at, updated_at)
            VALUES ('s1', 'Test', 'now', 'now');
            """
        )
        conn.execute(
            """
            INSERT INTO turns (
                turn_id, session_id, turn_index, role, content, token_count, created_at
            )
            VALUES ('t1', 's1', 0, 'user', 'hello', 5, 'now');
            """
        )
        conn.execute(
            """
            INSERT INTO journeys (journey_id, session_id, task, status, created_at)
            VALUES ('j1', 's1', 'task1', 'running', 'now');
            """
        )
        conn.execute(
            """
            INSERT INTO journey_steps (step_id, journey_id, step_index, node_name, created_at)
            VALUES ('st1', 'j1', 0, 'llm_node', 'now');
            """
        )

        turns_count = conn.execute(
            "SELECT count(*) FROM turns WHERE session_id = 's1';"
        ).fetchone()[0]
        assert turns_count == 1

        journeys_count = conn.execute(
            "SELECT count(*) FROM journeys WHERE session_id = 's1';"
        ).fetchone()[0]
        assert journeys_count == 1

        steps_count = conn.execute(
            "SELECT count(*) FROM journey_steps WHERE journey_id = 'j1';"
        ).fetchone()[0]
        assert steps_count == 1

        # Delete parent session
        conn.execute("DELETE FROM sessions WHERE session_id = 's1';")

        # Verify cascades
        assert (
            conn.execute("SELECT count(*) FROM turns WHERE session_id = 's1';").fetchone()[0] == 0
        )
        assert (
            conn.execute("SELECT count(*) FROM journeys WHERE session_id = 's1';").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT count(*) FROM journey_steps WHERE journey_id = 'j1';").fetchone()[
                0
            ]
            == 0
        )
