"""Domain models for local-first observability, telemetry, and RCA proposals."""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TelemetryMetric(BaseModel):
    """Quantitative metric point captured locally."""

    metric_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    value: float
    labels: dict[str, str] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TelemetryEvent(BaseModel):
    """Discreet operational lifecycle milestone or alert."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    severity: Literal["info", "warning", "error", "critical"] = "info"
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TelemetrySpan(BaseModel):
    """Distributed tracing span representing an isolated operation."""

    span_id: str = Field(default_factory=lambda: f"span_{uuid.uuid4().hex[:12]}")
    trace_id: str
    parent_span_id: str | None = None
    subsystem: str
    name: str
    duration_ms: int = 0
    status: Literal["ok", "error"] = "ok"
    error: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SystemHealthReport(BaseModel):
    """Synthesized operational vitals score and diagnostic findings."""

    health_score: int = Field(ge=0, le=100)
    error_rate_percent: float = 0.0
    avg_latency_ms: float = 0.0
    total_turns_24h: int = 0
    tool_reliability: dict[str, float] = Field(default_factory=dict)
    database_sizes_mb: dict[str, float] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RCAProposal(BaseModel):
    """Root Cause Analysis and remediation proposal staged in 00_Inbox."""

    proposal_id: str = Field(default_factory=lambda: f"rca_{uuid.uuid4().hex[:8]}")
    title: str
    category: str = "proposals"
    tags: list[str] = Field(default_factory=lambda: ["rca", "health_audit", "proposal"])
    severity: Literal["low", "medium", "warning", "high", "critical"] = "warning"
    issue_summary: str
    telemetry_evidence: dict[str, Any] = Field(default_factory=dict)
    root_cause: str
    suggested_remediation: str
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
