"""Session and journey repository implementation using SQLite."""

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from agent_os.domain.session import JourneyRecord, SessionRecord, TurnRecord
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.storage.session_db import get_connection, init_db


class SessionRepository:
    """Repository for managing session persistence, turns, and sub-journey scratchpads."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_db(self.db_path)
        self._journey_repo = JourneyRepository(self.db_path)

    def create_session(self, title: str = "New Session") -> SessionRecord:
        """Create and persist a new interactive session."""
        session_id = f"sess_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, title, created_at, updated_at, is_archived)
                VALUES (?, ?, ?, ?, 0);
                """,
                (session_id, title, now_str, now_str),
            )

        return SessionRecord(
            session_id=session_id,
            title=title,
            created_at=now,
            updated_at=now,
            is_archived=False,
        )

    def get_session(self, session_id: str) -> SessionRecord | None:
        """Retrieve a session by ID or return None if not found."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT session_id, title, created_at, updated_at, is_archived
                FROM sessions
                WHERE session_id = ?;
                """,
                (session_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return SessionRecord(
            session_id=row["session_id"],
            title=row["title"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            is_archived=bool(row["is_archived"]),
        )

    def ensure_session(self, session_id: str, title: str | None = None) -> SessionRecord:
        """Retrieve existing session or create it idempotently if missing."""
        existing = self.get_session(session_id)
        if existing is not None:
            return existing

        now = datetime.now(UTC)
        now_str = now.isoformat()
        session_title = title or f"Session: {session_id}"
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO sessions (
                    session_id, title, created_at, updated_at, is_archived
                ) VALUES (?, ?, ?, ?, 0);
                """,
                (session_id, session_title, now_str, now_str),
            )
        return self.get_session(session_id) or SessionRecord(
            session_id=session_id,
            title=session_title,
            created_at=now,
            updated_at=now,
            is_archived=False,
        )

    def append_turn(
        self,
        session_id: str,
        role: Literal["system", "user", "assistant", "tool"] | str,
        content: str,
        token_count: int = 0,
    ) -> TurnRecord:
        """Append a turn to a session, monotonically incrementing turn_index."""
        turn_id = f"turn_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(MAX(turn_index), -1) + 1 AS next_index
                FROM turns
                WHERE session_id = ?;
                """,
                (session_id,),
            )
            next_index = int(cursor.fetchone()["next_index"])

            conn.execute(
                """
                INSERT INTO turns (
                    turn_id, session_id, turn_index, role, content, token_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (turn_id, session_id, next_index, role, content, token_count, now_str),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?;",
                (now_str, session_id),
            )

        return TurnRecord(
            turn_id=turn_id,
            session_id=session_id,
            turn_index=next_index,
            role=cast(Literal["system", "user", "assistant", "tool"], role),
            content=content,
            token_count=token_count,
            created_at=now,
        )

    def get_recent_turns(self, session_id: str, limit: int = 15) -> list[TurnRecord]:
        """Retrieve the most recent turns for a session in chronological order."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT * FROM (
                    SELECT turn_id, session_id, turn_index, role, content, token_count, created_at
                    FROM turns
                    WHERE session_id = ?
                    ORDER BY turn_index DESC
                    LIMIT ?
                )
                ORDER BY turn_index ASC;
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()

        return [
            TurnRecord(
                turn_id=row["turn_id"],
                session_id=row["session_id"],
                turn_index=row["turn_index"],
                role=row["role"],
                content=row["content"],
                token_count=row["token_count"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def count_turns(self, session_id: str) -> int:
        """Count total conversation turns for a session."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) AS total FROM turns WHERE session_id = ?;",
                (session_id,),
            )
            row = cursor.fetchone()
            return int(row["total"]) if row else 0

    def record_journey_start(self, session_id: str, task: str) -> JourneyRecord:
        """Initialize and persist a new journey in running status."""
        return self._journey_repo.record_journey_start(session_id, task)

    def record_journey_step(
        self,
        journey_id: str,
        node_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        duration_ms: int = 0,
    ) -> None:
        """Append an isolated worker execution step to the journey scratchpad."""
        self._journey_repo.record_journey_step(
            journey_id=journey_id,
            node_name=node_name,
            input_payload=input_payload,
            output_payload=output_payload,
            duration_ms=duration_ms,
        )

    def complete_journey(
        self,
        journey_id: str,
        status: Literal["running", "completed", "failed", "aborted"] | str,
        summary: str,
        artifacts: list[str],
        state_mutations: list[str],
        metrics: dict[str, int | float],
    ) -> JourneyRecord:
        """Complete a journey with final status and return envelope."""
        return self._journey_repo.complete_journey(
            journey_id=journey_id,
            status=status,
            summary=summary,
            artifacts=artifacts,
            state_mutations=state_mutations,
            metrics=metrics,
        )

    def get_journey(self, journey_id: str) -> JourneyRecord | None:
        """Retrieve a journey record by ID."""
        return self._journey_repo.get_journey(journey_id)

    def get_journey_scratchpad(self, journey_id: str) -> list[dict[str, Any]]:
        """Retrieve raw step telemetry sequence for isolated audit."""
        return self._journey_repo.get_journey_scratchpad(journey_id)
