"""SQLite database connection and schema initialization for ingredients.db."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

INGREDIENTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingredients (
    id TEXT NOT NULL,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    capability TEXT,
    verb TEXT,
    resource TEXT,
    scope TEXT,
    effect TEXT,
    description TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id, version)
);

CREATE INDEX IF NOT EXISTS idx_ingredients_kind_status ON ingredients(kind, status);
CREATE INDEX IF NOT EXISTS idx_ingredients_signature ON ingredients(verb, resource, scope);
CREATE INDEX IF NOT EXISTS idx_ingredients_content_hash ON ingredients(content_hash);

CREATE TABLE IF NOT EXISTS ingredient_vectors (
    ingredient_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    dim INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    vector_blob BLOB NOT NULL,
    PRIMARY KEY (ingredient_id, version, model_id)
);

CREATE INDEX IF NOT EXISTS idx_vectors_lookup ON ingredient_vectors(
    ingredient_id, version, model_id
);
"""


@contextmanager
def get_ingredient_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open, configure with WAL, and automatically close an SQLite ingredient connection."""
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


def init_ingredient_db(db_path: Path) -> None:
    """Initialize SQLite ingredients schema and indexes idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_ingredient_connection(db_path) as conn:
        conn.executescript(INGREDIENTS_SCHEMA_SQL)
