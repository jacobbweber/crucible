"""Read-only SQLite inspection helpers for the REPL."""

import sqlite3
from pathlib import Path
from typing import Any

DATABASES = {
    "session": "session_store.db",
    "facts": "memory_facts.db",
    "recipes": "recipes.db",
    "education": "education.db",
    "vault": "vault.db",
}


def open_readonly(data_dir: Path, db_key: str) -> sqlite3.Connection:
    """Open a named runtime database in SQLite read-only URI mode."""
    if db_key not in DATABASES:
        raise KeyError(f"Unknown db '{db_key}'. Choose from: {', '.join(DATABASES)}")
    path = (data_dir / DATABASES[db_key]).resolve()
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


def query(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def truncate_row(row: dict[str, Any], width: int = 80) -> dict[str, Any]:
    """Shorten long values (and hide raw ciphertext) for readable display."""
    out: dict[str, Any] = {}
    for key, val in row.items():
        if isinstance(val, bytes):
            out[key] = f"<{len(val)} bytes>"
        elif isinstance(val, str) and len(val) > width:
            out[key] = val[:width] + "…"
        else:
            out[key] = val
    return out
