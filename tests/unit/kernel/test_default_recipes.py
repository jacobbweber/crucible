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
    assert len(recipes) == 3

    # Check recipe IDs
    ids = {r.metadata.recipe_id for r in recipes}
    assert "self_health_audit" in ids
    assert "weekly_warehouse_graduation" in ids
    assert "deep_topic_synthesis" in ids

    # Check FTS5 intent matching
    health_matches = repo.match_intent("check system health errors and audit vitals")
    assert len(health_matches) >= 1
    assert health_matches[0].recipe.metadata.recipe_id == "self_health_audit"

    grad_matches = repo.match_intent("graduate inbox notes to knowledge")
    assert len(grad_matches) >= 1
    assert grad_matches[0].recipe.metadata.recipe_id == "weekly_warehouse_graduation"

    synth_matches = repo.match_intent("synthesize topic across past history")
    assert len(synth_matches) >= 1
    assert synth_matches[0].recipe.metadata.recipe_id == "deep_topic_synthesis"

    # Idempotent re-run
    ensure_default_recipes(repo)
    assert len(repo.list_recipes()) == 3
