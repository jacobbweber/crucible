"""SQLite storage repository for local-first telemetry metrics, events, and traces."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from agent_os.domain.telemetry import TelemetryEvent, TelemetryMetric, TelemetrySpan
from agent_os.infrastructure.storage.telemetry_db import (
    get_telemetry_connection,
    init_telemetry_db,
)


class TelemetryRepository:
    """Repository managing local telemetry persistence, health metrics, and span querying."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_telemetry_db(self.db_path)

    def record_metric(self, metric: TelemetryMetric) -> None:
        """Persist a single quantitative metric point."""
        labels_json = json.dumps(metric.labels)
        recorded_str = metric.recorded_at.isoformat()
        with get_telemetry_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO telemetry_metrics (metric_id, name, value, labels_json, recorded_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (metric.metric_id, metric.name, metric.value, labels_json, recorded_str),
            )

    def record_event(self, event: TelemetryEvent) -> None:
        """Persist a milestone, lifecycle alert, or operational event."""
        payload_json = json.dumps(event.payload)
        recorded_str = event.recorded_at.isoformat()
        with get_telemetry_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO telemetry_events (
                    event_id, event_type, severity, message, payload_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.severity,
                    event.message,
                    payload_json,
                    recorded_str,
                ),
            )

    def record_span(self, span: TelemetrySpan) -> None:
        """Persist a distributed tracing span."""
        attrs_json = json.dumps(span.attributes)
        started_str = span.started_at.isoformat()
        completed_str = span.completed_at.isoformat() if span.completed_at else None
        with get_telemetry_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO telemetry_spans (
                    span_id, trace_id, parent_span_id, subsystem, name,
                    duration_ms, status, error, attributes_json, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    span.span_id,
                    span.trace_id,
                    span.parent_span_id,
                    span.subsystem,
                    span.name,
                    span.duration_ms,
                    span.status,
                    span.error,
                    attrs_json,
                    started_str,
                    completed_str,
                ),
            )

    def get_recent_metrics(
        self, name: str | None = None, limit: int = 100
    ) -> list[TelemetryMetric]:
        """Query recent metric points ordered by timestamp descending."""
        sql = "SELECT metric_id, name, value, labels_json, recorded_at FROM telemetry_metrics"
        params: list[Any] = []
        if name:
            sql += " WHERE name = ?"
            params.append(name)
        sql += " ORDER BY recorded_at DESC LIMIT ?;"
        params.append(limit)

        with get_telemetry_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            TelemetryMetric(
                metric_id=r["metric_id"],
                name=r["name"],
                value=float(r["value"]),
                labels=json.loads(r["labels_json"]),
                recorded_at=datetime.fromisoformat(r["recorded_at"]),
            )
            for r in rows
        ]

    def get_recent_events(
        self, severity: str | None = None, limit: int = 50
    ) -> list[TelemetryEvent]:
        """Query recent operational events filtered optionally by severity."""
        sql = (
            "SELECT event_id, event_type, severity, message, payload_json, recorded_at "
            "FROM telemetry_events"
        )
        params: list[Any] = []
        if severity:
            sql += " WHERE severity = ?"
            params.append(severity)
        sql += " ORDER BY recorded_at DESC LIMIT ?;"
        params.append(limit)

        with get_telemetry_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            TelemetryEvent(
                event_id=r["event_id"],
                event_type=r["event_type"],
                severity=r["severity"],
                message=r["message"],
                payload=json.loads(r["payload_json"]),
                recorded_at=datetime.fromisoformat(r["recorded_at"]),
            )
            for r in rows
        ]

    def get_recent_spans(
        self, subsystem: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[TelemetrySpan]:
        """Query recent distributed spans with optional filtering."""
        sql = (
            "SELECT span_id, trace_id, parent_span_id, subsystem, name, duration_ms, "
            "status, error, attributes_json, started_at, completed_at FROM telemetry_spans"
        )
        conditions: list[str] = []
        params: list[Any] = []
        if subsystem:
            conditions.append("subsystem = ?")
            params.append(subsystem)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY started_at DESC LIMIT ?;"
        params.append(limit)

        with get_telemetry_connection(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()

        return [
            TelemetrySpan(
                span_id=r["span_id"],
                trace_id=r["trace_id"],
                parent_span_id=r["parent_span_id"],
                subsystem=r["subsystem"],
                name=r["name"],
                duration_ms=int(r["duration_ms"]),
                status=cast(Any, r["status"]),
                error=r["error"],
                attributes=json.loads(r["attributes_json"]),
                started_at=datetime.fromisoformat(r["started_at"]),
                completed_at=(
                    datetime.fromisoformat(r["completed_at"]) if r["completed_at"] else None
                ),
            )
            for r in rows
        ]

    def get_health_metrics_summary(self, since_hours: int = 24) -> dict[str, Any]:
        """Compute aggregate health stats over the specified rolling window."""
        cutoff = (datetime.now(UTC) - timedelta(hours=since_hours)).isoformat()

        with get_telemetry_connection(self.db_path) as conn:
            # 1. Total spans and error rate
            cursor = conn.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                       AVG(duration_ms) as avg_duration
                FROM telemetry_spans
                WHERE started_at >= ?;
                """,
                (cutoff,),
            )
            span_stats = cursor.fetchone()
            total_spans = int(span_stats["total"] or 0)
            error_spans = int(span_stats["errors"] or 0)
            avg_duration = float(span_stats["avg_duration"] or 0.0)

            # 2. Tool reliability
            tool_cursor = conn.execute(
                """
                SELECT name, COUNT(*) as attempts,
                       SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as successes
                FROM telemetry_spans
                WHERE subsystem = 'tool' AND started_at >= ?
                GROUP BY name;
                """,
                (cutoff,),
            )
            tool_stats: dict[str, float] = {}
            for r in tool_cursor.fetchall():
                att = int(r["attempts"] or 0)
                suc = int(r["successes"] or 0)
                tool_stats[r["name"]] = round((suc / att) * 100.0, 1) if att > 0 else 100.0

        error_rate = round((error_spans / total_spans) * 100.0, 2) if total_spans > 0 else 0.0
        health_score = max(0, min(100, int(100 - (error_rate * 2))))

        return {
            "health_score": health_score,
            "total_spans": total_spans,
            "error_spans": error_spans,
            "error_rate_percent": error_rate,
            "avg_duration_ms": round(avg_duration, 1),
            "tool_reliability": tool_stats,
            "window_hours": since_hours,
        }

    def prune_old_telemetry(self, retention_days: int = 30) -> int:
        """Prune telemetry metrics, events, and spans older than retention threshold."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        deleted = 0
        with get_telemetry_connection(self.db_path) as conn:
            c1 = conn.execute("DELETE FROM telemetry_metrics WHERE recorded_at < ?;", (cutoff,))
            c2 = conn.execute("DELETE FROM telemetry_events WHERE recorded_at < ?;", (cutoff,))
            c3 = conn.execute("DELETE FROM telemetry_spans WHERE started_at < ?;", (cutoff,))
            deleted = c1.rowcount + c2.rowcount + c3.rowcount
        return deleted
