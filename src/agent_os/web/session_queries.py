"""Database helper functions for Web UI session listing and inspection."""

from pathlib import Path
from typing import Any

from agent_os.infrastructure.storage.session_db import get_connection


def list_recent_sessions(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    """List recent active sessions ordered by last update timestamp.

    Args:
        db_path: Path to sessions.db.
        limit: Maximum number of sessions to return.

    Returns:
        List of session summary dictionaries.
    """
    if not db_path.exists():
        return []

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT session_id, title, created_at, updated_at, is_archived
            FROM sessions
            WHERE is_archived = 0
            ORDER BY updated_at DESC
            LIMIT ?;
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "session_id": r["session_id"],
                "title": r["title"] or "Untitled Chat",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "is_archived": bool(r["is_archived"]),
            }
        )
    return results


def get_session_turn_history(db_path: Path, session_id: str) -> list[dict[str, Any]]:
    """Retrieve full conversational turn history for a given session.

    Args:
        db_path: Path to sessions.db.
        session_id: Target session identifier.

    Returns:
        Chronological list of turn records.
    """
    if not db_path.exists():
        return []

    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT turn_id, session_id, turn_index, role, content, token_count, created_at
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index ASC;
            """,
            (session_id,),
        )
        rows = cursor.fetchall()

    results: list[dict[str, Any]] = []
    for r in rows:
        results.append(
            {
                "turn_id": r["turn_id"],
                "session_id": r["session_id"],
                "turn_index": r["turn_index"],
                "role": r["role"],
                "content": r["content"],
                "token_count": r["token_count"],
                "created_at": r["created_at"],
            }
        )
    return results
