"""Unit tests for SQLite education and SRS database initialization and foreign key cascades."""

import sqlite3
from pathlib import Path

import pytest

from agent_os.infrastructure.storage.education_db import (
    get_education_connection,
    init_education_db,
)


def test_init_education_db_creates_tables_and_indices(tmp_path: Path) -> None:
    """Verify tables topics, review_cards, and review_logs exist with cascade deletion."""
    db_file = tmp_path / "education.db"
    init_education_db(db_file)

    with get_education_connection(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        assert {"topics", "review_cards", "review_logs"}.issubset(tables)

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
        }
        assert "idx_review_cards_topic" in indices
        assert "idx_review_cards_due" in indices

        # Foreign key integrity check
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO review_cards (
                    card_id, topic_id, prompt, expected_answer, repetitions,
                    interval_days, ease_factor, due_date
                )
                VALUES ('c1', 'nonexistent_topic', 'Q', 'A', 0, 1, 2.5, '2026-10-05T00:00:00Z');
                """
            )

        # Insert topic, card, and review log
        conn.execute(
            """
            INSERT INTO topics (
                topic_id, title, category, current_stage, mastery_score,
                created_at, updated_at
            )
            VALUES ('t1', 'Distributed Consensus', 'sys', 'stage_1_primer', 0.0, 'now', 'now');
            """
        )
        conn.execute(
            """
            INSERT INTO review_cards (
                card_id, topic_id, prompt, expected_answer, repetitions,
                interval_days, ease_factor, due_date
            )
            VALUES ('c1', 't1', 'What is Paxos?', 'Consensus protocol', 0, 1, 2.5, 'now');
            """
        )
        conn.execute(
            """
            INSERT INTO review_logs (
                log_id, card_id, grade, reviewed_at, old_interval, new_interval
            )
            VALUES ('l1', 'c1', 4, 'now', 1, 6);
            """
        )

        assert conn.execute("SELECT count(*) FROM topics WHERE topic_id = 't1';").fetchone()[0] == 1
        assert (
            conn.execute("SELECT count(*) FROM review_cards WHERE card_id = 'c1';").fetchone()[0]
            == 1
        )
        assert (
            conn.execute("SELECT count(*) FROM review_logs WHERE log_id = 'l1';").fetchone()[0] == 1
        )

        # Delete topic and assert cascade deletion of cards and logs
        conn.execute("DELETE FROM topics WHERE topic_id = 't1';")

        assert conn.execute("SELECT count(*) FROM topics WHERE topic_id = 't1';").fetchone()[0] == 0
        assert (
            conn.execute("SELECT count(*) FROM review_cards WHERE card_id = 'c1';").fetchone()[0]
            == 0
        )
        assert (
            conn.execute("SELECT count(*) FROM review_logs WHERE log_id = 'l1';").fetchone()[0] == 0
        )
