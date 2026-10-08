"""Recipe semantic compatibility and triage matching for dynamic dispatch."""

import re

from agent_os.domain.recipe import RecipeMatch, RecipeRecord

WRITE_ACTION_WORDS = {
    "save",
    "write",
    "capture",
    "store",
    "create",
    "record",
    "stage",
    "draft",
    "export",
}


def is_recipe_compatible(task: str, recipe: RecipeRecord) -> bool:
    """Verify that candidate recipe required tools and purpose align with task verbs."""
    task_words = set(re.findall(r"\w+", task.lower()))
    has_write_intent = bool(task_words & WRITE_ACTION_WORDS)

    if has_write_intent:
        recipe_has_write = any(
            t.endswith(("_write", "_stage_rca", "_create", "_put")) or "write" in t or "stage" in t
            for t in recipe.metadata.required_tools
        )
        if not recipe_has_write:
            return False

    return True


def select_best_recipe_match(
    task: str,
    matches: list[RecipeMatch],
    threshold: float = 0.5,
) -> RecipeMatch | None:
    """Filter and select the highest scoring compatible recipe match above threshold."""
    for match in matches:
        if match.score < threshold:
            continue
        if is_recipe_compatible(task, match.recipe):
            return match
    return None
