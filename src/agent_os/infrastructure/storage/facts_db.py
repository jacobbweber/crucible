"""SQLite FTS5 database connection and schema initialization for atomic facts."""

import sqlite3
from pathlib import Path

FACTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    entity_key TEXT NOT NULL,
    fact_text TEXT NOT NULL,
    category TEXT NOT NULL,
    source_turn_id TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_entity_key ON facts(entity_key);
CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);

CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    fact_id UNINDEXED,
    entity_key,
    fact_text,
    category,
    content='facts',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS tbl_facts_ai AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, fact_id, entity_key, fact_text, category)
    VALUES (new.rowid, new.fact_id, new.entity_key, new.fact_text, new.category);
END;

CREATE TRIGGER IF NOT EXISTS tbl_facts_ad AFTER DELETE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact_id, entity_key, fact_text, category)
    VALUES('delete', old.rowid, old.fact_id, old.entity_key, old.fact_text, old.category);
END;

CREATE TRIGGER IF NOT EXISTS tbl_facts_au AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, fact_id, entity_key, fact_text, category)
    VALUES('delete', old.rowid, old.fact_id, old.entity_key, old.fact_text, old.category);
    INSERT INTO facts_fts(rowid, fact_id, entity_key, fact_text, category)
    VALUES (new.rowid, new.fact_id, new.entity_key, new.fact_text, new.category);
END;
"""


def get_facts_connection(db_path: Path) -> sqlite3.Connection:
    """Open and configure an SQLite database connection for facts."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_facts_db(db_path: Path) -> None:
    """Initialize SQLite facts schema, FTS5 virtual table, and triggers idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_facts_connection(db_path) as conn:
        conn.executescript(FACTS_SCHEMA_SQL)
