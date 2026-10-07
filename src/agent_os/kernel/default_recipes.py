"""Default recipe definitions and provisioning for common operational workflows."""

from datetime import UTC, datetime

from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository


def _build_health_audit_recipe() -> RecipeRecord:
    metadata = RecipeMetadata(
        recipe_id="self_health_audit",
        name="System Health Audit & Incident Remediation",
        description=(
            "Audit local system health vitals, error rates, and failure traces, "
            "staging an RCA proposal in 00_Inbox if reliability degradation is detected."
        ),
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["system", "health", "observability", "telemetry", "rca", "diagnostics"],
        required_tools=[
            "telemetry_get_health_summary",
            "telemetry_audit_errors",
            "telemetry_stage_rca",
        ],
        timeout_seconds=300,
    )
    body = (
        "# System Health Audit & Incident Remediation\n\n"
        "## Goal\n"
        "Audit the local node's operational vitals, error rates, and recent traces. "
        "If anomalies or recurring failures are detected, analyze root causes and draft an "
        "actionable RCA proposal in `00_Inbox`.\n\n"
        "## Procedural Steps\n"
        "1. Call `telemetry_get_health_summary` to inspect health score and error rates.\n"
        "2. If health score < 95 or error rate > 5%, call `telemetry_audit_errors` to "
        "review recent stack traces and failure events.\n"
        "3. Group related error patterns by subsystem and identify common failure modes.\n"
        "4. If a systemic defect is identified, call `telemetry_stage_rca` to stage a "
        "structured postmortem in `00_Inbox`.\n"
        "5. Provide a concise operational briefing summarizing findings and staged proposals.\n\n"
        "## Verification Criteria\n"
        "- Health score and error rates are accurately reported.\n"
        "- Any staged RCA proposal contains non-empty title, root cause, and remediation.\n"
    )
    now = datetime.now(UTC)
    return RecipeRecord(
        metadata=metadata,
        markdown_path="02_Resources/recipes/self_health_audit.md",
        body=body,
        created_at=now,
        updated_at=now,
    )


def _build_warehouse_graduation_recipe() -> RecipeRecord:
    metadata = RecipeMetadata(
        recipe_id="weekly_warehouse_graduation",
        name="Warehouse Inbox Review & Graduation",
        description=(
            "Scan staged notes in 00_Inbox, validate frontmatter tags and categories, "
            "resolve naming collisions, and graduate valid notes into 01_Knowledge."
        ),
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["warehouse", "inbox", "graduation", "knowledge", "notes", "organization"],
        required_tools=["warehouse_list_category", "warehouse_read", "warehouse_graduate_inbox"],
        timeout_seconds=300,
    )
    body = (
        "# Warehouse Inbox Review & Graduation\n\n"
        "## Goal\n"
        "Perform graduation of notes staged in `00_Inbox/`, ensuring frontmatter validity "
        "and organizing approved knowledge into `01_Knowledge/`.\n\n"
        "## Procedural Steps\n"
        "1. Call `warehouse_list_category` on `00_Inbox` to survey pending notes.\n"
        "2. Call `warehouse_graduate_inbox` to execute schema validation and routing.\n"
        "3. Review the graduation report output for graduated versus quarantined files.\n"
        "4. For quarantined notes, inspect failure reasons and report needed corrections.\n\n"
        "## Verification Criteria\n"
        "- Valid notes are moved into their respective category subfolders.\n"
        "- Quarantined notes remain safely in `00_Inbox/` with diagnostic reasons.\n"
    )
    now = datetime.now(UTC)
    return RecipeRecord(
        metadata=metadata,
        markdown_path="02_Resources/recipes/weekly_warehouse_graduation.md",
        body=body,
        created_at=now,
        updated_at=now,
    )


def _build_topic_synthesis_recipe() -> RecipeRecord:
    metadata = RecipeMetadata(
        recipe_id="deep_topic_synthesis",
        name="Cross-Session Topic Synthesis & Archival Research",
        description=(
            "Search past conversation turns across active sessions and cold archives "
            "to synthesize comprehensive knowledge notes on a target topic."
        ),
        execution_engine="react",
        target_model_tier="reasoning",
        tags=["search", "history", "synthesis", "archive", "knowledge", "research"],
        required_tools=["session_search_history", "warehouse_write", "warehouse_search"],
        timeout_seconds=300,
    )
    body = (
        "# Cross-Session Topic Synthesis & Archival Research\n\n"
        "## Goal\n"
        "Conduct historical research across hot (`sessions.db`) and cold (`sessions_archive.db`) "
        "databases, distilling key decisions and facts into a knowledge document.\n\n"
        "## Procedural Steps\n"
        "1. Call `session_search_history` with keywords and `include_archive=True`.\n"
        "2. Call `warehouse_search` to verify existing related knowledge notes.\n"
        "3. Synthesize findings into a summary with Background, Decisions, and References.\n"
        "4. Save synthesized note into `00_Inbox/` via `warehouse_write`.\n\n"
        "## Verification Criteria\n"
        "- Findings span both recent and cold-archived sessions when relevant.\n"
        "- Synthesized markdown is formatted with valid YAML frontmatter.\n"
    )
    now = datetime.now(UTC)
    return RecipeRecord(
        metadata=metadata,
        markdown_path="02_Resources/recipes/deep_topic_synthesis.md",
        body=body,
        created_at=now,
        updated_at=now,
    )


def ensure_default_recipes(recipe_repo: RecipeRepository) -> None:
    """Idempotently register core system execution recipes into recipes.db."""
    default_recipes = [
        _build_health_audit_recipe(),
        _build_warehouse_graduation_recipe(),
        _build_topic_synthesis_recipe(),
    ]
    for recipe in default_recipes:
        if recipe_repo.get_recipe(recipe.metadata.recipe_id) is None:
            recipe_repo.upsert_recipe(recipe)
