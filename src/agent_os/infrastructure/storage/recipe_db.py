"""SQLite FTS5 database connection and schema initialization for execution recipes."""

import sqlite3
from pathlib import Path

RECIPES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recipes (
    recipe_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    execution_engine TEXT NOT NULL,
    target_model_tier TEXT NOT NULL,
    tags_json TEXT NOT NULL,
    required_tools_json TEXT NOT NULL,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    markdown_path TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipes_name ON recipes(name);

CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    recipe_id UNINDEXED,
    name,
    description,
    tags_text,
    content='recipes',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS tbl_recipes_ai AFTER INSERT ON recipes BEGIN
    INSERT INTO recipes_fts(rowid, recipe_id, name, description, tags_text)
    VALUES (
        new.rowid,
        new.recipe_id,
        new.name,
        new.description,
        (SELECT coalesce(group_concat(value, ' '), '') FROM json_each(new.tags_json))
    );
END;

CREATE TRIGGER IF NOT EXISTS tbl_recipes_ad AFTER DELETE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, recipe_id, name, description, tags_text)
    VALUES (
        'delete',
        old.rowid,
        old.recipe_id,
        old.name,
        old.description,
        (SELECT coalesce(group_concat(value, ' '), '') FROM json_each(old.tags_json))
    );
END;

CREATE TRIGGER IF NOT EXISTS tbl_recipes_au AFTER UPDATE ON recipes BEGIN
    INSERT INTO recipes_fts(recipes_fts, rowid, recipe_id, name, description, tags_text)
    VALUES (
        'delete',
        old.rowid,
        old.recipe_id,
        old.name,
        old.description,
        (SELECT coalesce(group_concat(value, ' '), '') FROM json_each(old.tags_json))
    );
    INSERT INTO recipes_fts(rowid, recipe_id, name, description, tags_text)
    VALUES (
        new.rowid,
        new.recipe_id,
        new.name,
        new.description,
        (SELECT coalesce(group_concat(value, ' '), '') FROM json_each(new.tags_json))
    );
END;
"""


def get_recipe_connection(db_path: Path) -> sqlite3.Connection:
    """Open and configure an SQLite database connection for recipes."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_recipe_db(db_path: Path) -> None:
    """Initialize SQLite recipes schema, FTS5 virtual table, and triggers idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_recipe_connection(db_path) as conn:
        conn.executescript(RECIPES_SCHEMA_SQL)
