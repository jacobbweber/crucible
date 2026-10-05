"""SQLite database connection and schema initialization for education and SRS records."""

import sqlite3
from pathlib import Path

EDUCATION_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    topic_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    current_stage TEXT NOT NULL,
    mastery_score REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS review_cards (
    card_id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    repetitions INTEGER NOT NULL DEFAULT 0,
    interval_days INTEGER NOT NULL DEFAULT 1,
    ease_factor REAL NOT NULL DEFAULT 2.5,
    due_date TIMESTAMP NOT NULL,
    last_reviewed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_logs (
    log_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES review_cards(card_id) ON DELETE CASCADE,
    grade INTEGER NOT NULL CHECK(grade BETWEEN 0 AND 5),
    reviewed_at TIMESTAMP NOT NULL,
    old_interval INTEGER NOT NULL,
    new_interval INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_cards_topic ON review_cards(topic_id);
CREATE INDEX IF NOT EXISTS idx_review_cards_due ON review_cards(due_date);
"""


def get_education_connection(db_path: Path) -> sqlite3.Connection:
    """Open and configure an SQLite database connection with foreign key enforcement."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_education_db(db_path: Path) -> None:
    """Initialize SQLite education schema and indices idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_education_connection(db_path) as conn:
        conn.executescript(EDUCATION_SCHEMA_SQL)
