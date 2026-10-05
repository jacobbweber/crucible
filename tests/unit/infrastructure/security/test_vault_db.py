"""Unit tests for credential vault database initialization."""

from pathlib import Path

from agent_os.infrastructure.security.vault_db import get_vault_connection, init_vault_db


def test_init_db_creates_credentials_table(tmp_path: Path) -> None:
    """Verify table and index exist after initialization."""
    db_file = tmp_path / "credentials.db"
    init_vault_db(db_file)

    with get_vault_connection(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        assert "credentials" in tables

        indices = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index';").fetchall()
        }
        assert "idx_credentials_alias" in indices
