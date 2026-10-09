"""Unit tests for semantic recipe triage and intent compatibility matching."""

from agent_os.domain.recipe import RecipeMatch
from agent_os.kernel.default_recipes import (
    _build_warehouse_capture_recipe,
    _build_warehouse_graduation_recipe,
)
from agent_os.kernel.recipe_triage import is_recipe_compatible, select_best_recipe_match


def test_is_recipe_compatible_disqualifies_readonly_for_write_task() -> None:
    """Verify that a write/save task rejects a recipe with read-only tools."""
    grad_recipe = _build_warehouse_graduation_recipe()
    capture_recipe = _build_warehouse_capture_recipe()

    save_task = "Save the Okta overview and architecture notes to the warehouse"
    # Graduation recipe only has list, read, graduate_inbox -> should be disqualified
    assert not is_recipe_compatible(save_task, grad_recipe)

    # Capture recipe has warehouse_write -> compatible
    assert is_recipe_compatible(save_task, capture_recipe)


def test_is_recipe_compatible_allows_graduation_for_inbox_organization() -> None:
    """Verify that an inbox organization task allows weekly_warehouse_graduation."""
    grad_recipe = _build_warehouse_graduation_recipe()
    org_task = "Review 00_Inbox and graduate approved notes to knowledge vault"
    assert is_recipe_compatible(org_task, grad_recipe)


def test_select_best_recipe_match_filters_incompatible() -> None:
    """Verify select_best_recipe_match skips incompatible matches and selects valid one."""
    grad_recipe = _build_warehouse_graduation_recipe()
    capture_recipe = _build_warehouse_capture_recipe()

    save_task = "Will you save that note to our warehouse"

    # Suppose SQLite FTS5 returned grad_recipe first (higher BM25) and capture_recipe second
    matches = [
        RecipeMatch(recipe=grad_recipe, score=2.5),
        RecipeMatch(recipe=capture_recipe, score=1.8),
    ]

    selected = select_best_recipe_match(save_task, matches, threshold=0.5)
    assert selected is not None
    assert selected.recipe.metadata.recipe_id == "warehouse_capture_note"


def test_select_best_recipe_match_returns_none_if_no_write_tools_for_write_task() -> None:
    """If catalog only has read-only matches for a save task, fallback to ephemeral assembly."""
    grad_recipe = _build_warehouse_graduation_recipe()
    save_task = "Save our discussion on kubernetes pods to warehouse"

    matches = [RecipeMatch(recipe=grad_recipe, score=3.0)]
    selected = select_best_recipe_match(save_task, matches, threshold=0.5)
    assert selected is None
