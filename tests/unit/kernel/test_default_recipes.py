"""Unit tests verifying pre-seeded catalog execution recipes."""

from pathlib import Path

from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.kernel.default_recipes import ensure_default_recipes


def test_ensure_default_recipes_seeds_catalog(tmp_path: Path) -> None:
    """Verify default system recipes are seeded into recipes.db and matchable."""
    db_path = tmp_path / "recipes.db"
    repo = RecipeRepository(db_path)

    # Initially empty
    assert len(repo.list_recipes()) == 0

    # Seed recipes
    ensure_default_recipes(repo)
    recipes = repo.list_recipes()
    assert len(recipes) == 6

    # Check recipe IDs
    ids = {r.metadata.recipe_id for r in recipes}
    assert "self_health_audit" in ids
    assert "warehouse_capture_note" in ids
    assert "weekly_warehouse_graduation" in ids
    assert "deep_topic_synthesis" in ids
    assert "docker_container_orchestration" in ids
    assert "custom_tool_authoring" in ids

    # Check FTS5 intent matching
    health_matches = repo.match_intent("check system health errors and audit vitals")
    assert len(health_matches) >= 1
    assert health_matches[0].recipe.metadata.recipe_id == "self_health_audit"

    capture_matches = repo.match_intent("save notes and capture overview to warehouse")
    assert len(capture_matches) >= 1
    assert capture_matches[0].recipe.metadata.recipe_id == "warehouse_capture_note"

    docker_matches = repo.match_intent("inspect docker containers and logs")
    assert len(docker_matches) >= 1
    assert docker_matches[0].recipe.metadata.recipe_id == "docker_container_orchestration"

    author_matches = repo.match_intent("synthesize custom fastmcp tool")
    assert len(author_matches) >= 1
    assert author_matches[0].recipe.metadata.recipe_id == "custom_tool_authoring"

    # Idempotent re-run
    ensure_default_recipes(repo)
    assert len(repo.list_recipes()) == 6

