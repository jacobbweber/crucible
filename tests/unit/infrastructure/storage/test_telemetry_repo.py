"""Unit tests for TelemetryRepository persistence and health aggregation."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_os.domain.telemetry import TelemetryEvent, TelemetryMetric, TelemetrySpan
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository


@pytest.fixture
def repo(tmp_path: Path) -> TelemetryRepository:
    db_path = tmp_path / "telemetry.db"
    return TelemetryRepository(db_path)


def test_record_and_get_metrics(repo: TelemetryRepository):
    m1 = TelemetryMetric(name="token_latency", value=42.5, labels={"model": "vllm"})
    m2 = TelemetryMetric(name="token_latency", value=48.0, labels={"model": "vllm"})
    m3 = TelemetryMetric(name="context_tokens", value=1200.0)

    repo.record_metric(m1)
    repo.record_metric(m2)
    repo.record_metric(m3)

    latencies = repo.get_recent_metrics("token_latency")
    assert len(latencies) == 2
    assert latencies[0].name == "token_latency"

    all_metrics = repo.get_recent_metrics()
    assert len(all_metrics) == 3


def test_record_and_get_events(repo: TelemetryRepository):
    e1 = TelemetryEvent(event_type="policy_block", severity="warning", message="Tool blocked")
    e2 = TelemetryEvent(event_type="boot", severity="info", message="Kernel started")

    repo.record_event(e1)
    repo.record_event(e2)

    warnings = repo.get_recent_events(severity="warning")
    assert len(warnings) == 1
    assert warnings[0].event_type == "policy_block"


def test_record_spans_and_health_summary(repo: TelemetryRepository):
    now = datetime.now(UTC)
    # Record 3 tool spans: 2 ok, 1 error
    s1 = TelemetrySpan(
        trace_id="trc_1",
        subsystem="tool",
        name="web_fetch",
        duration_ms=120,
        status="ok",
        started_at=now,
    )
    s2 = TelemetrySpan(
        trace_id="trc_1",
        subsystem="tool",
        name="web_fetch",
        duration_ms=150,
        status="ok",
        started_at=now,
    )
    s3 = TelemetrySpan(
        trace_id="trc_2",
        subsystem="tool",
        name="web_fetch",
        duration_ms=500,
        status="error",
        error="Timeout",
        started_at=now,
    )

    repo.record_span(s1)
    repo.record_span(s2)
    repo.record_span(s3)

    error_spans = repo.get_recent_spans(status="error")
    assert len(error_spans) == 1
    assert error_spans[0].error == "Timeout"

    summary = repo.get_health_metrics_summary(since_hours=24)
    assert summary["total_spans"] == 3
    assert summary["error_spans"] == 1
    assert summary["error_rate_percent"] == 33.33
    assert summary["tool_reliability"]["web_fetch"] == 66.7


def test_prune_old_telemetry(repo: TelemetryRepository):
    old_time = datetime.now(UTC) - timedelta(days=45)
    s_old = TelemetrySpan(
        trace_id="trc_old",
        subsystem="tool",
        name="old_tool",
        duration_ms=50,
        status="ok",
        started_at=old_time,
    )
    m_old = TelemetryMetric(name="old_m", value=1.0, recorded_at=old_time)
    e_old = TelemetryEvent(event_type="old_ev", message="old", recorded_at=old_time)

    repo.record_span(s_old)
    repo.record_metric(m_old)
    repo.record_event(e_old)

    deleted = repo.prune_old_telemetry(retention_days=30)
    assert deleted == 3

    assert len(repo.get_recent_spans()) == 0
    assert len(repo.get_recent_metrics()) == 0
    assert len(repo.get_recent_events()) == 0
