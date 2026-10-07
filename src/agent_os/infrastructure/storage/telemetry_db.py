"""SQLite connection and schema initialization for local telemetry storage."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

TELEMETRY_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS telemetry_metrics (
    metric_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    labels_json TEXT NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry_spans (
    span_id TEXT PRIMARY KEY,
    trace_id TEXT NOT NULL,
    parent_span_id TEXT,
    subsystem TEXT NOT NULL,
    name TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    error TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_recorded ON telemetry_metrics(name, recorded_at);
CREATE INDEX IF NOT EXISTS idx_events_severity_recorded ON telemetry_events(severity, recorded_at);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON telemetry_spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_subsystem_status ON telemetry_spans(subsystem, status);
CREATE INDEX IF NOT EXISTS idx_spans_started ON telemetry_spans(started_at);
"""


@contextmanager
def get_telemetry_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open, configure with WAL, and automatically close an SQLite telemetry connection."""
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


def init_telemetry_db(db_path: Path) -> None:
    """Initialize SQLite database tables and indices for telemetry idempotently."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_telemetry_connection(db_path) as conn:
        conn.executescript(TELEMETRY_SCHEMA_SQL)
