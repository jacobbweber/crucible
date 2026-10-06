"""SQLite connection and schema initialization for the encrypted credential vault."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

VAULT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS credentials (
    credential_id TEXT PRIMARY KEY,
    alias TEXT UNIQUE NOT NULL,
    cred_type TEXT NOT NULL CHECK(
        cred_type IN ('api_key', 'basic_auth', 'oauth2', 'ssh_key', 'tls_cert')
    ),
    encrypted_payload BLOB NOT NULL,
    metadata_json TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_credentials_alias ON credentials(alias);
"""


@contextmanager
def get_vault_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open, configure with WAL, and automatically close an SQLite vault connection."""
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


def init_vault_db(db_path: Path) -> None:
    """Initialize credential vault schema and index idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_vault_connection(db_path) as conn:
        conn.executescript(VAULT_SCHEMA_SQL)
