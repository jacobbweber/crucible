"""Unit tests for RecipePromoter and on-demand workflow promotion into 00_Inbox."""

from pathlib import Path

import pytest

from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.recipe_promoter import RecipePromoter, slugify_recipe_id


@pytest.fixture
def temp_env(tmp_path: Path):
    db_path = tmp_path / "sessions.db"
    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)
    session_repo = SessionRepository(db_path)
    journey_repo = JourneyRepository(db_path)
    wiki_store = WikiStore(warehouse_dir)
    return journey_repo, session_repo, wiki_store, warehouse_dir


def test_slugify_recipe_id():
    assert slugify_recipe_id("Sync Vault Data") == "sync_vault_data"
    assert slugify_recipe_id("  Clean Logs! (v2)  ") == "clean_logs_v2"
    assert slugify_recipe_id("") == "promoted_recipe"


def test_promote_journey_to_inbox(temp_env):
    journey_repo, session_repo, wiki_store, warehouse_dir = temp_env
    session_repo.ensure_session("sess_abc")
    promoter = RecipePromoter(journey_repo=journey_repo, wiki_store=wiki_store)

    # Record a completed journey with steps
    journey = journey_repo.record_journey_start("sess_abc", "backup postgres database")
    journey_repo.record_journey_step(
        journey_id=journey.journey_id,
        node_name="pg_dump_tool",
        input_payload={"db": "prod"},
        output_payload={"status": "dumped"},
        duration_ms=45,
    )
    journey_repo.record_journey_step(
        journey_id=journey.journey_id,
        node_name="s3_upload_tool",
        input_payload={"bucket": "backups"},
        output_payload={"status": "uploaded"},
        duration_ms=120,
    )
    journey_repo.complete_journey(
        journey_id=journey.journey_id,
        status="completed",
        summary="Database dumped and archived to S3 bucket",
        artifacts=["prod.sql.gz"],
        state_mutations=[],
        metrics={"duration_ms": 165},
    )

    staged_path = promoter.promote_journey(
        journey_id=journey.journey_id,
        recipe_name="Database Backup Flow",
        description="Automated backup and upload to S3",
    )

    # 1. Verify path is in 00_Inbox (The Sacred Rule of 00_Inbox)
    assert staged_path.exists()
    assert staged_path.parent == warehouse_dir / ProtectedFolder.INBOX.value
    assert staged_path.name == "database_backup_flow.md"

    # 2. Verify file content structure
    content = staged_path.read_text(encoding="utf-8")
    assert 'title: "Recipe: Database Backup Flow"' in content
    assert 'category: "recipes"' in content
    assert "- pg_dump_tool" in content
    assert "- s3_upload_tool" in content
    assert "Execute `pg_dump_tool`" in content
    assert "Execute `s3_upload_tool`" in content

    # 3. Verify GraduationService graduates this note into 01_Knowledge/recipes/
    grad_service = GraduationService(wiki_store)
    report = grad_service.execute_graduation()
    assert report.graduated_count == 1
    assert report.failed_count == 0

    target_knowledge_folder = (
        ProtectedFolder.KNOWLEDGE.value
        if (warehouse_dir / ProtectedFolder.KNOWLEDGE.value).exists()
        else ProtectedFolder.NOTES.value
    )
    graduated_file = warehouse_dir / target_knowledge_folder / "recipes" / "database_backup_flow.md"
    assert graduated_file.exists()
    assert not staged_path.exists()  # Removed from 00_Inbox upon graduation


def test_promote_recent_for_session(temp_env):
    journey_repo, session_repo, wiki_store, warehouse_dir = temp_env
    session_repo.ensure_session("sess_xyz")
    promoter = RecipePromoter(journey_repo=journey_repo, wiki_store=wiki_store)

    # Record two journeys in session
    j1 = journey_repo.record_journey_start("sess_xyz", "first task")
    journey_repo.complete_journey(j1.journey_id, "completed", "first done", [], [], {})

    j2 = journey_repo.record_journey_start("sess_xyz", "second task")
    journey_repo.complete_journey(j2.journey_id, "completed", "second done", [], [], {})

    staged_path = promoter.promote_recent_for_session(
        session_id="sess_xyz",
        recipe_name="Second Task Workflow",
    )
    assert staged_path.exists()
    assert staged_path.name == "second_task_workflow.md"
    content = staged_path.read_text(encoding="utf-8")
    assert "second task" in content


def test_promote_journey_not_completed_raises(temp_env):
    journey_repo, session_repo, wiki_store, _ = temp_env
    session_repo.ensure_session("sess_fail")
    promoter = RecipePromoter(journey_repo=journey_repo, wiki_store=wiki_store)

    j = journey_repo.record_journey_start("sess_fail", "unfinished task")
    with pytest.raises(ValueError, match="not completed"):
        promoter.promote_journey(j.journey_id, "Unfinished")
