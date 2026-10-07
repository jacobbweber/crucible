"""Observability collector managing distributed tracing spans, metrics, and health synthesis."""

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_os.domain.telemetry import (
    SystemHealthReport,
    TelemetryEvent,
    TelemetryMetric,
    TelemetrySpan,
)
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository


class TelemetryCollector:
    """Collects spans, metrics, and events locally and compiles operational health reports."""

    def __init__(self, repo: TelemetryRepository) -> None:
        self.repo = repo

    @asynccontextmanager
    async def trace_operation(
        self,
        name: str,
        subsystem: str,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> AsyncIterator[TelemetrySpan]:
        """Async context manager tracing an operation with automatic duration calculation."""
        actual_trace_id = trace_id or f"trc_{uuid.uuid4().hex[:12]}"
        span = TelemetrySpan(
            trace_id=actual_trace_id,
            parent_span_id=parent_span_id,
            subsystem=subsystem,
            name=name,
            attributes=attributes or {},
            started_at=datetime.now(UTC),
        )
        start_time = time.perf_counter()
        try:
            yield span
            span.status = "ok"
        except Exception as exc:
            span.status = "error"
            span.error = str(exc)
            raise
        finally:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
            span.duration_ms = elapsed_ms
            span.completed_at = datetime.now(UTC)
            self.repo.record_span(span)

    def record_counter(
        self, name: str, value: float = 1.0, labels: dict[str, str] | None = None
    ) -> None:
        """Record a quantitative counter or rate metric."""
        metric = TelemetryMetric(name=name, value=value, labels=labels or {})
        self.repo.record_metric(metric)

    def record_event(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Record an operational lifecycle event or alert."""
        event = TelemetryEvent(
            event_type=event_type,
            severity=severity,  # type: ignore[arg-type]
            message=message,
            payload=payload or {},
        )
        self.repo.record_event(event)

    def compile_health_report(
        self,
        db_paths: list[Path] | None = None,
        hours: int = 24,
    ) -> SystemHealthReport:
        """Synthesize aggregate health metrics and compile diagnostic findings."""
        summary = self.repo.get_health_metrics_summary(since_hours=hours)
        findings: list[str] = []

        # 1. Evaluate tool failure rates
        tool_reliability = summary["tool_reliability"]
        for tool_name, reliability in tool_reliability.items():
            if reliability < 80.0:
                fail_pct = 100.0 - reliability
                findings.append(
                    f"Tool '{tool_name}' failure rate is elevated ({fail_pct:.1f}% failures)."
                )

        # 2. Evaluate error rate
        err_pct = summary["error_rate_percent"]
        if err_pct > 10.0:
            findings.append(f"Overall system error rate is {err_pct:.1f}% over the last {hours}h.")

        # 3. Check database file footprints
        db_sizes: dict[str, float] = {}
        if db_paths:
            for p in db_paths:
                if p.exists():
                    size_mb = round(p.stat().st_size / (1024 * 1024), 2)
                    db_sizes[p.name] = size_mb
                    if size_mb > 50.0:
                        findings.append(
                            f"Database '{p.name}' is large ({size_mb} MB); maintenance recommended."
                        )

        health_score = summary["health_score"]
        if findings and health_score > 90:
            health_score = 90 - (len(findings) * 5)
        health_score = max(0, min(100, health_score))

        return SystemHealthReport(
            health_score=health_score,
            error_rate_percent=summary["error_rate_percent"],
            avg_latency_ms=summary["avg_duration_ms"],
            total_turns_24h=summary["total_spans"],
            tool_reliability=tool_reliability,
            database_sizes_mb=db_sizes,
            findings=findings,
        )
