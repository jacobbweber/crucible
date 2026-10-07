"""Unit tests for TelemetryToolSuite providing health summaries and RCA staging."""

import json
from pathlib import Path

import pytest

from agent_os.domain.telemetry import TelemetrySpan
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.rca_stager import RcaProposalStager
from agent_os.kernel.telemetry_tools import TelemetryToolSuite


@pytest.fixture
def suite_env(tmp_path: Path):
    db_path = tmp_path / "telemetry.db"
    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)

    repo = TelemetryRepository(db_path)
    stager = RcaProposalStager(WikiStore(warehouse_dir))
    suite = TelemetryToolSuite(
        telemetry_repo=repo,
        rca_stager=stager,
        db_paths=[db_path],
    )
    return suite, repo, warehouse_dir


def test_telemetry_get_health_summary(suite_env):
    suite, repo, _ = suite_env

    # Record sample ok and error spans
    repo.record_span(
        TelemetrySpan(
            trace_id="trc_1",
            subsystem="tool",
            name="wiki_read",
            duration_ms=50,
            status="ok",
        )
    )

    res = suite.telemetry_get_health_summary(hours=24)
    assert res.success is True
    data = json.loads(res.output)
    assert "health_score" in data
    assert data["health_score"] <= 100
    assert "telemetry.db" in data["database_sizes_mb"]


def test_telemetry_audit_errors(suite_env):
    suite, repo, _ = suite_env

    repo.record_span(
        TelemetrySpan(
            trace_id="trc_err",
            subsystem="tool",
            name="failing_tool",
            duration_ms=100,
            status="error",
            error="Connection refused",
        )
    )

    res = suite.telemetry_audit_errors(limit=5)
    assert res.success is True
    errors = json.loads(res.output)
    assert len(errors) == 1
    assert "Connection refused" in errors[0]["error"]


def test_telemetry_stage_rca(suite_env):
    suite, _, warehouse_dir = suite_env

    res = suite.telemetry_stage_rca(
        title="Excessive Database Locking",
        issue_summary="SQLite write locks observed exceeding 2000ms.",
        root_cause="WAL checkpoint contention during background batch processing.",
        suggested_fix="Run PRAGMA wal_checkpoint(PASSIVE) in smaller chunks.",
        severity="high",
    )
    assert res.success is True
    assert "Successfully staged RCA proposal" in res.output

    inbox_files = list((warehouse_dir / ProtectedFolder.INBOX.value).glob("*.md"))
    assert len(inbox_files) == 1
    assert inbox_files[0].name == "rca_excessive_database_locking.md"
