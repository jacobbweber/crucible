"""Journey and worker execution scratchpad repository using SQLite."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from agent_os.domain.session import JourneyRecord
from agent_os.infrastructure.storage.session_db import get_connection, init_db


class JourneyRepository:
    """Repository for managing sub-journey execution scratchpads and audit logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_db(self.db_path)

    def record_journey_start(self, session_id: str, task: str) -> JourneyRecord:
        """Initialize and persist a new journey in running status."""
        journey_id = f"jrn_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO journeys (
                    journey_id, session_id, task, status, summary,
                    artifacts_json, state_mutations_json, metrics_json,
                    created_at, completed_at
                ) VALUES (?, ?, ?, 'running', NULL, '[]', '[]', '{}', ?, NULL);
                """,
                (journey_id, session_id, task, now_str),
            )

        return JourneyRecord(
            journey_id=journey_id,
            session_id=session_id,
            task=task,
            status="running",
            summary=None,
            artifacts=[],
            state_mutations=[],
            metrics={},
            created_at=now,
            completed_at=None,
        )

    def record_journey_step(
        self,
        journey_id: str,
        node_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        duration_ms: int = 0,
    ) -> None:
        """Append an isolated worker execution step to the journey scratchpad."""
        step_id = f"step_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()
        input_json = json.dumps(input_payload)
        output_json = json.dumps(output_payload)

        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT COALESCE(MAX(step_index), -1) + 1 AS next_index
                FROM journey_steps
                WHERE journey_id = ?;
                """,
                (journey_id,),
            )
            next_index = int(cursor.fetchone()["next_index"])

            conn.execute(
                """
                INSERT INTO journey_steps (
                    step_id, journey_id, step_index, node_name,
                    input_payload_json, output_payload_json, duration_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    step_id,
                    journey_id,
                    next_index,
                    node_name,
                    input_json,
                    output_json,
                    duration_ms,
                    now_str,
                ),
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
        now = datetime.now(UTC)
        now_str = now.isoformat()
        artifacts_json = json.dumps(artifacts)
        mutations_json = json.dumps(state_mutations)
        metrics_json = json.dumps(metrics)

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE journeys
                SET status = ?, summary = ?, artifacts_json = ?,
                    state_mutations_json = ?, metrics_json = ?, completed_at = ?
                WHERE journey_id = ?;
                """,
                (
                    status,
                    summary,
                    artifacts_json,
                    mutations_json,
                    metrics_json,
                    now_str,
                    journey_id,
                ),
            )

        record = self.get_journey(journey_id)
        if record is None:
            raise ValueError(f"Journey not found: {journey_id}")
        return record

    def get_journey(self, journey_id: str) -> JourneyRecord | None:
        """Retrieve a journey record by ID."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT journey_id, session_id, task, status, summary,
                       artifacts_json, state_mutations_json, metrics_json,
                       created_at, completed_at
                FROM journeys
                WHERE journey_id = ?;
                """,
                (journey_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        completed_at = datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None

        return JourneyRecord(
            journey_id=row["journey_id"],
            session_id=row["session_id"],
            task=row["task"],
            status=row["status"],
            summary=row["summary"],
            artifacts=json.loads(row["artifacts_json"]),
            state_mutations=json.loads(row["state_mutations_json"]),
            metrics=json.loads(row["metrics_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=completed_at,
        )

    def get_journey_scratchpad(self, journey_id: str) -> list[dict[str, Any]]:
        """Retrieve raw step telemetry sequence for isolated audit."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT step_id, journey_id, step_index, node_name,
                       input_payload_json, output_payload_json, duration_ms, created_at
                FROM journey_steps
                WHERE journey_id = ?
                ORDER BY step_index ASC;
                """,
                (journey_id,),
            )
            rows = cursor.fetchall()

        return [
            {
                "step_id": row["step_id"],
                "journey_id": row["journey_id"],
                "step_index": row["step_index"],
                "node_name": row["node_name"],
                "input_payload": json.loads(row["input_payload_json"]),
                "output_payload": json.loads(row["output_payload_json"]),
                "duration_ms": row["duration_ms"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
