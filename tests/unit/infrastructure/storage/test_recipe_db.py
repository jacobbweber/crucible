"""Unit tests for SQLite FTS5 recipe database initialization, indices, and triggers."""

from pathlib import Path

from agent_os.infrastructure.storage.recipe_db import (
    get_recipe_connection,
    init_recipe_db,
)


def test_init_recipe_db_creates_tables_and_triggers(tmp_path: Path) -> None:
    """Verify recipes table, recipes_fts virtual table, index, and triggers exist."""
    db_file = tmp_path / "recipes.db"
    init_recipe_db(db_file)

    with get_recipe_connection(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        assert "recipes" in tables
        assert "recipes_fts" in tables

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
        }
        assert "idx_recipes_name" in indices

        triggers = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger';"
            ).fetchall()
        }
        assert "tbl_recipes_ai" in triggers
        assert "tbl_recipes_ad" in triggers
        assert "tbl_recipes_au" in triggers
