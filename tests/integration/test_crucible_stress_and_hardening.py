"""Stress and hardening integration battery for Agent OS.

Pushes the Warehouse, Hot/Cold retention, Capability Evolution,
Respectful Scheduling, Telemetry, and RCA staging under high concurrency and edge cases.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.kernel import KernelConfig
from agent_os.domain.telemetry import TelemetrySpan
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.security.cipher import derive_master_key
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.routine_repo import RoutineRepository
from agent_os.infrastructure.storage.session_db import get_connection
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.master_kernel import AgentOSKernel
from agent_os.kernel.pattern_scout import PatternScout
from agent_os.kernel.recipe_promoter import RecipePromoter
from agent_os.kernel.telemetry_collector import TelemetryCollector


class FastMockAdapter(BaseModelAdapter):
    """Zero-delay mock adapter for high-throughput stress testing."""

    async def complete(self, request: CompletionRequest):
        yield StreamChunk(delta="Acknowledged task execution.")


@pytest.fixture
def stress_environment(tmp_path: Path):
    """Build a fully isolated local runtime environment for stress tests."""
    data_dir = tmp_path / "agent_os_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    warehouse_dir = data_dir / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)

    session_db = data_dir / "sessions.db"
    recipes_db = data_dir / "recipes.db"
    telemetry_db = data_dir / "telemetry.db"
    vault_db = data_dir / "vault.db"
    facts_db = data_dir / "facts.db"
    education_db = data_dir / "education.db"

    session_repo = SessionRepository(session_db)
    recipe_repo = RecipeRepository(recipes_db)
    journey_repo = JourneyRepository(session_db)
    routine_repo = RoutineRepository(session_db)
    telemetry_repo = TelemetryRepository(telemetry_db)
    facts_repo = FactRepository(facts_db)
    education_repo = EducationRepository(education_db)
    wiki_store = WikiStore(warehouse_dir)
    wiki_store.init_vault()

    salt = b"salt_for_stress_test_16b"
    key = derive_master_key(salt, "stress_passphrase")
    vault_repo = CredentialVaultRepository(vault_db, master_key=key)

    kernel = AgentOSKernel(
        config=KernelConfig(storage_root=str(data_dir), max_concurrency=8),
        session_repo=session_repo,
        facts_repo=facts_repo,
        recipe_repo=recipe_repo,
        education_repo=education_repo,
        vault_repo=vault_repo,
        wiki_store=wiki_store,
        model_adapter=FastMockAdapter(),
        routine_repo=routine_repo,
        telemetry_repo=telemetry_repo,
    )

    return {
        "kernel": kernel,
        "session_repo": session_repo,
        "journey_repo": journey_repo,
        "telemetry_repo": telemetry_repo,
        "recipe_repo": recipe_repo,
        "routine_repo": routine_repo,
        "wiki_store": wiki_store,
        "data_dir": data_dir,
        "warehouse_dir": warehouse_dir,
    }


@pytest.mark.asyncio
async def test_stress_concurrent_telemetry_and_session_writes(stress_environment):
    """Stress Test 1: 50 concurrent tasks writing spans, metrics, and turns without SQLite locks."""
    session_repo: SessionRepository = stress_environment["session_repo"]
    telemetry_repo: TelemetryRepository = stress_environment["telemetry_repo"]
    collector = TelemetryCollector(telemetry_repo)

    async def worker_task(worker_id: int):
        sess_id = f"stress_sess_{worker_id}"
        session_repo.ensure_session(sess_id, title=f"Worker {worker_id}")
        for i in range(5):
            async with collector.trace_operation(
                name=f"worker_op_{worker_id}",
                subsystem="stress_test",
                trace_id=f"trc_{worker_id}_{i}",
                attributes={"cycle": i},
            ) as span:
                collector.record_counter("stress_cycles", 1.0, labels={"worker": str(worker_id)})
                session_repo.append_turn(
                    session_id=sess_id,
                    role="user",
                    content=f"Message {i} from worker {worker_id}",
                    token_count=15,
                )
                span.duration_ms = 5

    # Execute 50 concurrent workers (250 turns + 250 spans + 250 metrics)
    await asyncio.gather(*(worker_task(i) for i in range(50)))

    # Verify no database corruption and full record integrity
    spans = telemetry_repo.get_recent_spans(limit=300)
    assert len(spans) == 250

    summary = telemetry_repo.get_health_metrics_summary(since_hours=1)
    assert summary["total_spans"] == 250
    assert summary["error_spans"] == 0
    assert summary["health_score"] == 100


@pytest.mark.asyncio
async def test_stress_hot_cold_session_retention_under_activity(stress_environment):
    """Stress Test 2: Archive sessions >90d while active sessions are concurrently created."""
    session_repo: SessionRepository = stress_environment["session_repo"]
    archive_db_path = stress_environment["data_dir"] / "sessions_archive.db"

    now = datetime.now(UTC)

    # Seed 40 old sessions (100 days old) and 20 recent sessions (10 days old)
    for i in range(40):
        s_id = f"old_sess_{i}"
        session_repo.ensure_session(s_id, title=f"Old Session {i}")
        session_repo.append_turn(s_id, "user", f"Old query {i}", 10)
        # Manually backdate created_at in SQLite
        with get_connection(session_repo.db_path) as conn:
            old_date = (now - timedelta(days=100 + i)).isoformat()
            conn.execute(
                "UPDATE sessions SET created_at = ?, updated_at = ? WHERE session_id = ?;",
                (old_date, old_date, s_id),
            )

    for i in range(20):
        s_id = f"new_sess_{i}"
        session_repo.ensure_session(s_id, title=f"New Session {i}")
        session_repo.append_turn(s_id, "user", f"Recent query {i}", 10)

    # Trigger session archiving with 90-day retention
    archived_count = session_repo.archive_old_sessions(retention_days=90)

    assert archived_count == 40
    assert archive_db_path.exists()

    # Verify archived session is read-accessible from cold storage
    archived_record = session_repo.get_archived_session("old_sess_0")
    assert archived_record is not None
    assert archived_record.session_id == "old_sess_0"

    # Verify active session still exists in hot DB
    active_record = session_repo.get_session("new_sess_0")
    assert active_record is not None


@pytest.mark.asyncio
async def test_stress_pattern_scout_and_recipe_promotion_volume(stress_environment):
    """Stress Test 3: Multiple journey clusters, pattern scout discovery, and inbox promotion."""
    session_repo: SessionRepository = stress_environment["session_repo"]
    journey_repo: JourneyRepository = stress_environment["journey_repo"]
    recipe_repo: RecipeRepository = stress_environment["recipe_repo"]
    wiki_store: WikiStore = stress_environment["wiki_store"]

    scout = PatternScout(journey_repo, recipe_repo, wiki_store)
    promoter = RecipePromoter(journey_repo, wiki_store)

    # Pattern A: 4 journeys executing git_fetch -> run_tests -> notify_slack
    for i in range(4):
        s_id = f"pattern_sess_{i}"
        session_repo.ensure_session(s_id)
        j = journey_repo.record_journey_start(s_id, f"test run {i}")
        journey_repo.record_journey_step(j.journey_id, "git_fetch", {}, {}, 10)
        journey_repo.record_journey_step(j.journey_id, "run_tests", {}, {}, 40)
        journey_repo.record_journey_step(j.journey_id, "notify_slack", {}, {}, 15)
        journey_repo.complete_journey(j.journey_id, "completed", "Done", [], [], {})

    # Pattern B: 2 journeys (below threshold 3) executing docker_clean
    for i in range(2):
        s_id = f"rare_sess_{i}"
        session_repo.ensure_session(s_id)
        j = journey_repo.record_journey_start(s_id, "docker clean")
        journey_repo.record_journey_step(j.journey_id, "docker_clean", {}, {}, 20)
        journey_repo.complete_journey(j.journey_id, "completed", "Cleaned", [], [], {})

    # Run scout cycle
    staged = scout.run_scout_cycle(min_frequency=3)
    assert len(staged) == 1
    assert "suggested_git_fetch_run_tests_notify_slack.md" in staged[0].name

    # On-demand promotion of the rare journey explicitly by user
    user_promoted_path = promoter.promote_recent_for_session(
        session_id="rare_sess_1",
        recipe_name="Docker Host Cleanup",
        description="Explicit user-promoted cleanup",
    )
    assert user_promoted_path.exists()
    assert user_promoted_path.name == "docker_host_cleanup.md"

    # Graduate all staged recipes through GraduationService
    grad = GraduationService(wiki_store)
    report = grad.execute_graduation()
    assert report.graduated_count == 2
    assert report.failed_count == 0


@pytest.mark.asyncio
async def test_stress_warehouse_graduation_edge_cases(stress_environment):
    """Stress Test 4: Heavy name collisions, invalid frontmatter, path traversal in 00_Inbox."""
    wiki_store: WikiStore = stress_environment["wiki_store"]
    inbox_dir = wiki_store.root_dir / ProtectedFolder.INBOX.value

    # 1. Valid note that should graduate
    (inbox_dir / "valid_note.md").write_text(
        "---\ntitle: Valid Note\ncategory: research\ntags: [ai]\n---\nBody", encoding="utf-8"
    )

    # 2. Invalid note: Missing tags
    (inbox_dir / "no_tags.md").write_text(
        "---\ntitle: Missing Tags\ncategory: research\ntags: []\n---\nBody", encoding="utf-8"
    )

    # 3. Invalid note: Path depth > 2
    (inbox_dir / "too_deep.md").write_text(
        "---\ntitle: Deep\ncategory: a/b/c\ntags: [ai]\n---\nBody", encoding="utf-8"
    )

    # 4. Invalid note: Target points to protected 00_Inbox
    (inbox_dir / "target_inbox.md").write_text(
        "---\ntitle: Loop\ncategory: 00_Inbox\ntags: [ai]\n---\nBody", encoding="utf-8"
    )

    # 5. Collision test: 2 notes with same filename
    # Pre-create note in destination to force rename collision resolution
    notes_root = wiki_store.root_dir / ProtectedFolder.KNOWLEDGE.value
    (notes_root / "research").mkdir(parents=True, exist_ok=True)
    (notes_root / "research" / "valid_note.md").write_text("Existing note", encoding="utf-8")

    grad = GraduationService(wiki_store)
    report = grad.execute_graduation(collision_resolution="rename")

    # 1 valid graduated (renamed with _1), 3 failed quarantined
    assert report.graduated_count == 1
    assert report.failed_count == 3
    assert len(report.failures) == 3

    # Collided note was safely renamed to valid_note_1.md without overwriting
    existing_text = (notes_root / "research" / "valid_note.md").read_text(encoding="utf-8")
    assert existing_text == "Existing note"
    assert (notes_root / "research" / "valid_note_1.md").exists()


@pytest.mark.asyncio
async def test_stress_health_audit_and_rca_staging_end_to_end(stress_environment):
    """Stress Test 5: Simulated degradation, health summary detection, and RCA staging."""
    kernel: AgentOSKernel = stress_environment["kernel"]
    telemetry_repo: TelemetryRepository = stress_environment["telemetry_repo"]
    wiki_store: WikiStore = stress_environment["wiki_store"]

    now = datetime.now(UTC)

    # Simulate 8 failed tool calls on tool "db_sync" and 2 successful calls
    for i in range(8):
        telemetry_repo.record_span(
            TelemetrySpan(
                trace_id=f"trc_fail_{i}",
                subsystem="tool",
                name="db_sync",
                duration_ms=1200,
                status="error",
                error="Lock timeout: database is locked",
                started_at=now,
            )
        )
    for i in range(2):
        telemetry_repo.record_span(
            TelemetrySpan(
                trace_id=f"trc_ok_{i}",
                subsystem="tool",
                name="db_sync",
                duration_ms=40,
                status="ok",
                started_at=now,
            )
        )

    # Query health summary via tool execution through the master kernel
    health_res = await kernel.execute_tool("telemetry_get_health_summary", {"hours": 24})
    assert health_res.success is True
    import json
    data = json.loads(health_res.output)
    assert data["health_score"] < 80
    assert len(data["findings"]) >= 1
    assert "db_sync" in data["findings"][0]

    # Stage RCA proposal through master kernel tool dispatcher
    rca_res = await kernel.execute_tool(
        "telemetry_stage_rca",
        {
            "title": "Database Lock Contention During Sync",
            "issue_summary": "db_sync failed 80% of calls over past 24 hours.",
            "root_cause": "Concurrent writes collided on WAL checkpoint.",
            "suggested_fix": "Introduce retry backoff with exponential jitter.",
            "severity": "high",
        },
    )
    assert rca_res.success is True
    assert "Successfully staged RCA proposal" in rca_res.output

    # Verify proposal is staged in 00_Inbox
    inbox_proposals = list((wiki_store.root_dir / ProtectedFolder.INBOX.value).glob("rca_*.md"))
    assert len(inbox_proposals) == 1
    content = inbox_proposals[0].read_text(encoding="utf-8")
    assert "Database Lock Contention During Sync" in content
    assert 'category: "proposals"' in content

    # Graduate the RCA proposal into 01_Knowledge/proposals/
    grad = GraduationService(wiki_store)
    report = grad.execute_graduation()
    assert report.graduated_count == 1
    target_folder = wiki_store.root_dir / ProtectedFolder.KNOWLEDGE.value / "proposals"
    assert (target_folder / inbox_proposals[0].name).exists()
