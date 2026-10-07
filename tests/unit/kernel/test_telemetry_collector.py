"""Unit tests for TelemetryCollector tracing context manager and health synthesis."""

from pathlib import Path

import pytest

from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.kernel.telemetry_collector import TelemetryCollector


@pytest.fixture
def collector(tmp_path: Path):
    db_path = tmp_path / "telemetry.db"
    repo = TelemetryRepository(db_path)
    return TelemetryCollector(repo), repo, tmp_path


@pytest.mark.asyncio
async def test_trace_operation_success(collector):
    col, repo, _ = collector

    async with col.trace_operation(
        name="sample_query", subsystem="gateway", trace_id="trc_abc"
    ) as span:
        assert span.trace_id == "trc_abc"
        assert span.name == "sample_query"

    spans = repo.get_recent_spans()
    assert len(spans) == 1
    assert spans[0].status == "ok"
    assert spans[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_trace_operation_error(collector):
    col, repo, _ = collector

    with pytest.raises(RuntimeError, match="Simulated crash"):
        async with col.trace_operation(name="failing_op", subsystem="runner"):
            raise RuntimeError("Simulated crash")

    spans = repo.get_recent_spans()
    assert len(spans) == 1
    assert spans[0].status == "error"
    assert "Simulated crash" in (spans[0].error or "")


def test_compile_health_report(collector):
    col, repo, tmp_path = collector

    # Record metrics and events
    col.record_counter("turn_count", 5.0)
    col.record_event("alert", "High memory usage", severity="warning")

    # Create dummy database file to test footprint detection
    dummy_db = tmp_path / "sessions.db"
    dummy_db.write_bytes(b"0" * 1024)

    report = col.compile_health_report(db_paths=[dummy_db], hours=24)
    assert report.health_score <= 100
    assert "sessions.db" in report.database_sizes_mb
