"""Unit tests for SQLite FTS5 facts database initialization and triggers."""

from pathlib import Path

from agent_os.infrastructure.storage.facts_db import get_facts_connection, init_facts_db


def test_init_db_creates_tables_and_triggers(tmp_path: Path) -> None:
    """Verify facts table, facts_fts virtual table, indices, and triggers exist."""
    db_file = tmp_path / "memory_facts.db"
    init_facts_db(db_file)

    with get_facts_connection(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        assert "facts" in tables
        assert "facts_fts" in tables

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
        }
        assert "idx_facts_entity_key" in indices
        assert "idx_facts_category" in indices

        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger';"
            ).fetchall()
        }
        assert "tbl_facts_ai" in triggers
        assert "tbl_facts_ad" in triggers
        assert "tbl_facts_au" in triggers
