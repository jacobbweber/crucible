"""Unit tests for After-Hours Pattern Scout analyzing journey telemetry."""

from pathlib import Path

import pytest

from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.wiki import ProtectedFolder
from agent_os.infrastructure.storage.journey_repo import JourneyRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.graduation import GraduationService
from agent_os.kernel.pattern_scout import PatternScout
from agent_os.kernel.signaling import CompletionSignaler


@pytest.fixture
def temp_scout_env(tmp_path: Path):
    session_db = tmp_path / "sessions.db"
    recipe_db = tmp_path / "recipes.db"
    warehouse_dir = tmp_path / "warehouse"
    warehouse_dir.mkdir(parents=True, exist_ok=True)

    session_repo = SessionRepository(session_db)
    journey_repo = JourneyRepository(session_db)
    recipe_repo = RecipeRepository(recipe_db)
    wiki_store = WikiStore(warehouse_dir)
    signaler = CompletionSignaler()

    return journey_repo, recipe_repo, wiki_store, signaler, session_repo, warehouse_dir


def test_pattern_scout_discovers_repeated_sequences(temp_scout_env):
    journey_repo, recipe_repo, wiki_store, signaler, session_repo, warehouse_dir = temp_scout_env
    scout = PatternScout(
        journey_repo=journey_repo,
        recipe_repo=recipe_repo,
        wiki_store=wiki_store,
        signaler=signaler,
    )

    # Simulate 3 journeys executing the same sequence: git_pull -> npm_build -> test_runner
    for i in range(3):
        session_repo.ensure_session(f"sess_{i}")
        j = journey_repo.record_journey_start(f"sess_{i}", f"build and test release {i}")
        journey_repo.record_journey_step(j.journey_id, "git_pull", {}, {}, 10)
        journey_repo.record_journey_step(j.journey_id, "npm_build", {}, {}, 50)
        journey_repo.record_journey_step(j.journey_id, "test_runner", {}, {}, 100)
        journey_repo.complete_journey(j.journey_id, "completed", "Build completed", [], [], {})

    # Simulate 1 one-off journey with different tools (should NOT trigger pattern)
    session_repo.ensure_session("sess_rare")
    j_rare = journey_repo.record_journey_start("sess_rare", "one-off task")
    journey_repo.record_journey_step(j_rare.journey_id, "disk_cleanup", {}, {}, 5)
    journey_repo.complete_journey(j_rare.journey_id, "completed", "Cleaned disk", [], [], {})

    # Run scout cycle with min_frequency=3
    staged = scout.run_scout_cycle(min_frequency=3)
    assert len(staged) == 1

    candidate_file = staged[0]
    assert candidate_file.exists()
    assert candidate_file.parent == warehouse_dir / ProtectedFolder.INBOX.value
    assert candidate_file.name == "suggested_git_pull_npm_build_test_runner.md"

    # Verify content structure
    content = candidate_file.read_text(encoding="utf-8")
    assert 'category: "recipes"' in content
    assert "- pattern_scout" in content
    assert "- candidate" in content
    assert "- git_pull" in content
    assert "- npm_build" in content
    assert "- test_runner" in content

    # Verify ambient discovery nudge was signaled
    nudges = signaler.poll_ambient_nudges()
    assert len(nudges) >= 1
    discovery_nudge = next(n for n in nudges if n.status == "discovery")
    assert "Good morning!" in discovery_nudge.short_notice
    assert "suggested_git_pull_npm_build_test_runner" in discovery_nudge.journey_id

    # Verify GraduationService can graduate this discovered candidate
    grad_service = GraduationService(wiki_store)
    report = grad_service.execute_graduation()
    assert report.graduated_count == 1
    assert report.failed_count == 0


def test_pattern_scout_skips_existing_catalog_recipes(temp_scout_env):
    journey_repo, recipe_repo, wiki_store, signaler, session_repo, _ = temp_scout_env

    # Register an existing recipe with git_pull and npm_build
    recipe_repo.upsert_recipe(
        RecipeRecord(
            metadata=RecipeMetadata(
                recipe_id="existing_build",
                name="Existing Build Recipe",
                description="Existing",
                execution_engine="react",
                target_model_tier="reasoning",
                tags=["build"],
                required_tools=["git_pull", "npm_build"],
            ),
            markdown_path="recipes/existing_build.md",
            body="Existing body",
        )
    )

    # Simulate 3 journeys executing git_pull -> npm_build
    for i in range(3):
        session_repo.ensure_session(f"sess_{i}")
        j = journey_repo.record_journey_start(f"sess_{i}", f"build release {i}")
        journey_repo.record_journey_step(j.journey_id, "git_pull", {}, {}, 10)
        journey_repo.record_journey_step(j.journey_id, "npm_build", {}, {}, 50)
        journey_repo.complete_journey(j.journey_id, "completed", "Build completed", [], [], {})

    scout = PatternScout(
        journey_repo=journey_repo,
        recipe_repo=recipe_repo,
        wiki_store=wiki_store,
        signaler=signaler,
    )
    staged = scout.run_scout_cycle(min_frequency=3)
    assert len(staged) == 0  # Skipped because catalog already has this toolset!
