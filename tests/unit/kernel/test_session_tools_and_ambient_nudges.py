"""Unit tests for dual-database session history search and ambient discovery nudges."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_os.domain.telemetry import TelemetrySpan
from agent_os.infrastructure.storage.routine_repo import RoutineRepository
from agent_os.infrastructure.storage.session_db import get_connection
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.default_routines import ensure_default_routines
from agent_os.kernel.rca_stager import RcaProposalStager
from agent_os.kernel.session_tools import SessionToolSuite
from agent_os.kernel.signaling import CompletionSignaler
from agent_os.kernel.telemetry_tools import TelemetryToolSuite


def test_dual_database_session_search(tmp_path: Path) -> None:
    """Verify session search locates turns across both hot and cold SQLite archives."""
    hot_db = tmp_path / "sessions.db"
    archive_db = tmp_path / "sessions_archive.db"

    repo = SessionRepository(db_path=hot_db, archive_db_path=archive_db)

    # 1. Create hot session
    s_hot = repo.create_session(title="Recent Proxmox Deployment")
    repo.append_turn(s_hot.session_id, "user", "How do I configure Proxmox VE clustering?", 10)
    repo.append_turn(s_hot.session_id, "assistant", "Use pvecm create cluster-name on node 1.", 20)

    # 2. Create old session and backdate it
    s_old = repo.create_session(title="Old Docker Setup")
    repo.append_turn(s_old.session_id, "user", "How do I restart the Docker daemon safely?", 10)
    repo.append_turn(
        s_old.session_id, "assistant", "Run systemctl restart docker or docker service restart.", 20
    )

    now = datetime.now(UTC)
    old_ts = (now - timedelta(days=120)).isoformat()
    with get_connection(hot_db) as conn:
        conn.execute(
            "UPDATE sessions SET created_at = ?, updated_at = ? WHERE session_id = ?;",
            (old_ts, old_ts, s_old.session_id),
        )

    # 3. Archive old session to cold storage
    archived_count = repo.archive_old_sessions(retention_days=90)
    assert archived_count == 1
    assert archive_db.exists()

    # 4. Search across both hot and cold storage
    suite = SessionToolSuite(repo)

    # Search for "Proxmox" (hot)
    hot_res = suite.session_search_history("Proxmox", include_archive=True)
    assert hot_res.success is True
    hot_data = json.loads(hot_res.output)
    assert hot_data["count"] == 2
    assert hot_data["matches"][0]["is_archived"] is False

    # Search for "Docker" (cold)
    cold_res = suite.session_search_history("Docker", include_archive=True)
    assert cold_res.success is True
    cold_data = json.loads(cold_res.output)
    assert cold_data["count"] == 2
    assert cold_data["matches"][0]["is_archived"] is True
    assert "docker" in cold_data["matches"][0]["snippet"].lower()

    # Search with include_archive=False should miss cold records
    only_hot = suite.session_search_history("Docker", include_archive=False)
    assert only_hot.success is True
    assert "No conversation history matched" in only_hot.output


def test_ambient_discovery_nudges_and_prompt_injection() -> None:
    """Verify signal_discovery queues both UI ambient nudges and prompt injection block."""
    signaler = CompletionSignaler()

    signaler.signal_discovery(
        session_id="sess_123",
        message="Discovered recurring pattern: git_fetch -> run_tests",
        pattern_id="scout_pattern_1",
    )

    # Check prompt injection block
    prompt_block = signaler.format_deferred_prompt_block("sess_123")
    assert "<background_completions>" in prompt_block
    assert "[Discovery Notice] Discovered recurring pattern" in prompt_block

    # Notice is drained after formatting
    empty_block = signaler.format_deferred_prompt_block("sess_123")
    assert empty_block == ""

    # Check ambient UI nudges
    nudges = signaler.poll_ambient_nudges(session_id="sess_123")
    assert len(nudges) == 1
    assert nudges[0].status == "discovery"
    assert "Discovered recurring pattern" in nudges[0].short_notice


def test_telemetry_rca_signals_ambient_nudge(tmp_path: Path) -> None:
    """Verify staging an RCA proposal automatically triggers ambient discovery signal."""
    telemetry_db = tmp_path / "telemetry.db"
    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir()

    repo = TelemetryRepository(telemetry_db)
    store = WikiStore(warehouse_dir)
    store.init_vault()
    stager = RcaProposalStager(store)
    signaler = CompletionSignaler()

    suite = TelemetryToolSuite(
        telemetry_repo=repo,
        rca_stager=stager,
        signaler=signaler,
    )

    res = suite.telemetry_stage_rca(
        title="High Disk IO Contention",
        issue_summary="Spike in IO latency during backup.",
        root_cause="Concurrent sqlite backups collided.",
        suggested_fix="Stagger backup cron schedule.",
        severity="high",
    )
    assert res.success is True

    # Verify discovery signal was pushed
    nudges = signaler.poll_ambient_nudges()
    assert len(nudges) == 1
    assert "High Disk IO Contention" in nudges[0].short_notice

    # Verify prompt block injection
    prompt_block = signaler.format_deferred_prompt_block("any_session")
    assert "High Disk IO Contention" in prompt_block


def test_telemetry_prune_old_records_tool(tmp_path: Path) -> None:
    """Verify telemetry_prune_old_records tool prunes records and returns count."""
    telemetry_db = tmp_path / "telemetry.db"
    repo = TelemetryRepository(telemetry_db)
    store = WikiStore(tmp_path / "warehouse")
    stager = RcaProposalStager(store)
    suite = TelemetryToolSuite(telemetry_repo=repo, rca_stager=stager)

    # Insert old span (40 days old) and recent span (5 days old)
    now = datetime.now(UTC)
    repo.record_span(
        TelemetrySpan(
            trace_id="trc_old",
            subsystem="tool",
            name="test_tool",
            duration_ms=10,
            status="ok",
            started_at=now - timedelta(days=40),
        )
    )
    repo.record_span(
        TelemetrySpan(
            trace_id="trc_recent",
            subsystem="tool",
            name="test_tool",
            duration_ms=10,
            status="ok",
            started_at=now - timedelta(days=5),
        )
    )

    prune_res = suite.telemetry_prune_old_records(retention_days=30)
    assert prune_res.success is True
    assert "Successfully pruned" in prune_res.output

    remaining = repo.get_recent_spans(limit=10)
    assert len(remaining) == 1
    assert remaining[0].trace_id == "trc_recent"


def test_ensure_default_routines(tmp_path: Path) -> None:
    """Verify ensure_default_routines idempotently registers maintenance routine."""
    session_db = tmp_path / "sessions.db"
    repo = RoutineRepository(session_db)

    ensure_default_routines(repo)
    routine = repo.get_routine("routine_weekly_telemetry_prune")
    assert routine is not None
    assert routine.catch_up_policy == "skip_to_next"
    assert "telemetry_prune_old_records" in routine.task_payload

    # Re-running is idempotent
    ensure_default_routines(repo)
    assert len(repo.list_routines()) == 1
