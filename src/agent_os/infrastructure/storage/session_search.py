"""Dual-database history search across active and cold archived sessions."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os.infrastructure.storage.session_db import get_connection


@dataclass
class SessionHistoryMatch:
    """Structured representation of a matched turn across hot or cold storage."""

    session_id: str
    session_title: str
    turn_id: str
    turn_index: int
    role: str
    snippet: str
    created_at: str
    is_archived: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert match record to dictionary."""
        return {
            "session_id": self.session_id,
            "session_title": self.session_title,
            "turn_id": self.turn_id,
            "turn_index": self.turn_index,
            "role": self.role,
            "snippet": self.snippet,
            "created_at": self.created_at,
            "is_archived": self.is_archived,
        }


def _extract_snippet(content: str, query: str, max_chars: int = 140) -> str:
    """Extract a concise surrounding text window containing query words."""
    lower_content = content.lower()
    lower_query = query.lower()
    idx = lower_content.find(lower_query)
    if idx == -1:
        # Fallback to first query token
        tokens = [t for t in lower_query.split() if t]
        for token in tokens:
            idx = lower_content.find(token)
            if idx != -1:
                break

    if idx == -1:
        ellipsis = "..." if len(content) > max_chars else ""
        return content[:max_chars].strip().replace("\n", " ") + ellipsis

    start = max(0, idx - 40)
    end = min(len(content), idx + len(query) + 80)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return prefix + content[start:end].strip().replace("\n", " ") + suffix


def search_session_history(
    db_path: Path,
    archive_db_path: Path | None,
    query: str,
    limit: int = 10,
    include_archive: bool = True,
) -> list[SessionHistoryMatch]:
    """Search interactive session turns across hot and cold SQLite databases.

    Args:
        db_path: Path to hot sessions.db.
        archive_db_path: Path to cold sessions_archive.db.
        query: Search term or substring to locate across turns and titles.
        limit: Maximum number of matches to return.
        include_archive: Whether to query cold archive storage if available.

    Returns:
        Sorted list of SessionHistoryMatch objects by timestamp descending.
    """
    clean_query = query.strip()
    if not clean_query or limit <= 0:
        return []

    sql_pattern = f"%{clean_query}%"
    matches: list[SessionHistoryMatch] = []

    def _query_db(target_path: Path, is_cold: bool) -> None:
        if not target_path.exists():
            return
        query_sql = """
            SELECT t.turn_id, t.session_id, t.turn_index, t.role, t.content, t.created_at, s.title
            FROM turns t
            JOIN sessions s ON t.session_id = s.session_id
            WHERE t.content LIKE ? OR s.title LIKE ?
            ORDER BY t.created_at DESC
            LIMIT ?;
        """
        with get_connection(target_path) as conn:
            cursor = conn.execute(query_sql, (sql_pattern, sql_pattern, limit))
            for row in cursor.fetchall():
                snippet = _extract_snippet(row["content"], clean_query)
                matches.append(
                    SessionHistoryMatch(
                        session_id=row["session_id"],
                        session_title=row["title"],
                        turn_id=row["turn_id"],
                        turn_index=row["turn_index"],
                        role=row["role"],
                        snippet=snippet,
                        created_at=row["created_at"],
                        is_archived=is_cold,
                    )
                )

    # 1. Query Hot Sessions DB
    _query_db(db_path, is_cold=False)

    # 2. Query Cold Archive DB if enabled
    if include_archive and archive_db_path is not None:
        _query_db(archive_db_path, is_cold=True)

    # Sort combined matches chronologically descending
    def _parse_ts(ts_str: str) -> datetime:
        try:
            return datetime.fromisoformat(ts_str)
        except Exception:
            return datetime.min

    matches.sort(key=lambda m: _parse_ts(m.created_at), reverse=True)
    return matches[:limit]
