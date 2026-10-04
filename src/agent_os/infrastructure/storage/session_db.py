"""SQLite connection and schema initialization for session and journey storage."""

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    is_archived INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    turn_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS journeys (
    journey_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    task TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT,
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    state_mutations_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journey_steps (
    step_id TEXT PRIMARY KEY,
    journey_id TEXT NOT NULL REFERENCES journeys(journey_id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    node_name TEXT NOT NULL,
    input_payload_json TEXT NOT NULL DEFAULT '{}',
    output_payload_json TEXT NOT NULL DEFAULT '{}',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_turns_session_turn ON turns(session_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_journeys_session ON journeys(session_id);
CREATE INDEX IF NOT EXISTS idx_journey_steps_journey_step ON journey_steps(journey_id, step_index);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open and configure an SQLite database connection with foreign key enforcement."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path) -> None:
    """Initialize SQLite database schema and indices idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
