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

VAULT_KEYWORDS = {
    "warehouse",
    "vault",
    "note",
    "notes",
    "inbox",
    "obsidian",
    "knowledge",
    "lesson",
    "summary",
    "reference",
    "study",
    "capture",
}

HOST_PATH_PATTERNS = [
    r"[a-zA-Z]:[\\/]",
    r"(?:^|\s)/(?:home|etc|var|usr|bin|tmp|opt|root|mnt)/",
]


def is_recipe_compatible(task: str, recipe: RecipeRecord) -> bool:
    """Verify that candidate recipe required tools and purpose align with task verbs and domain."""
    lower_task = task.lower()
    task_words = set(re.findall(r"\w+", lower_task))
    recipe_id = recipe.metadata.recipe_id
    req_tools = recipe.metadata.required_tools

    # 1. Host filesystem path check: if task targets a host path/drive, warehouse vault tools cannot fulfill it
    has_host_path = any(re.search(p, task) for p in HOST_PATH_PATTERNS) or any(
        k in lower_task for k in ["drive", "desktop", "host machine", "local machine"]
    )
    only_vault_tools = all(t.startswith(("warehouse_", "wiki_", "session_")) for t in req_tools)
    if has_host_path and only_vault_tools:
        return False

    # 2. Warehouse note capture check: task must actually target saving notes or knowledge
    if "warehouse_capture_note" in recipe_id or "warehouse_graduation" in recipe_id:
        if not (task_words & VAULT_KEYWORDS):
            return False

    # 3. Telemetry health check: task must target observability / diagnostics
    if "health_audit" in recipe_id or any("telemetry" in t for t in req_tools):
        health_words = {"health", "audit", "telemetry", "error", "errors", "vital", "vitals", "rca", "diagnostic", "diagnostics"}
        if not (task_words & health_words):
            return False

    # 4. Docker check: task must target containers / docker
    if "docker" in recipe_id:
        docker_words = {"docker", "container", "containers", "compose", "pod", "homelab"}
        if not (task_words & docker_words):
            return False

    # 5. Write intent check
    has_write_intent = bool(task_words & WRITE_ACTION_WORDS)
    if has_write_intent:
        recipe_has_write = any(
            t.endswith(("_write", "_stage_rca", "_create", "_put")) or "write" in t or "stage" in t
            for t in req_tools
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
