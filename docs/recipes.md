# Recipes & Tools Reference

> **Purpose**: Describes how recipes and tools work **today**, and where the design is going.
>
> [!IMPORTANT]
> The recipe layer is being rebuilt under [ADR-0015](adr/0015-contract-first-ingredients-and-structured-intent-resolution.md) (Phases 17–25 in the [roadmap](steering/roadmap.md)). Sections 1–3 describe current behavior so expectations match the code. Section 4 summarizes the target design.

---

## 1. Current Recipe Model (pre-ADR-0015)

Recipes are rows in `recipes.db` (SQLite + FTS5). They are **not** markdown files in the vault. Schema ([`RecipeMetadata`](../src/agent_os/domain/recipe.py)):

| Field | Type | Notes |
|---|---|---|
| `recipe_id` | str | Primary key |
| `name`, `description` | str | Indexed in FTS5 |
| `tags` | list[str] | Indexed in FTS5 |
| `execution_engine` | `direct` \| `react` \| `plan_execute_verify` \| `stategraph` | Runner modality |
| `target_model_tier` | `fast` \| `reasoning` \| `coding` | Stored; not yet used for routing |
| `required_tools` | list[str] | Tool names only; no parameter or output contracts |
| `timeout_seconds` | int | Enforced by the runner |
| `body` | str | Markdown runbook, used as the worker system prompt |

Seeded recipes are defined in [`default_recipes.py`](../src/agent_os/kernel/default_recipes.py).

## 2. Current Lookup Behavior (known-fragile)

1. `RecipeRepository.match_intent` runs an FTS5 BM25 query that ORs every non-stop-word in the task.
2. `recipe_triage.select_best_recipe_match` applies a score threshold and hardcoded keyword compatibility rules.
3. On no match, the dispatcher asks the model for a JSON task brief and runs an ephemeral worker.
4. If the capability scout reports a gap, the toolsmith synthesizes a tool, dry-runs it, mounts it, and auto-creates a recipe.

Steps 1, 2 and 4 rely on keyword heuristics tracked as finding **R1**. They will be removed in Phase 21.

## 3. Built-in Tools

All tools are registered by the kernel with an `ActionTier` (`read`, `state_change`, `destructive`) that the policy gate evaluates.

| Suite | Tools |
|---|---|
| Wiki / vault | `wiki_read`, `wiki_write`, `wiki_search`, `wiki_list_category`, `wiki_graduate_inbox` (each also aliased as `warehouse_*`) |
| Session history | `session_search_history` |
| Education | `education_record_grade`, `education_advance_stage` |
| Telemetry | `telemetry_get_health_summary`, `telemetry_audit_errors`, `telemetry_stage_rca`, `telemetry_prune_old_records` |
| Workspace | `workspace_read`, `workspace_write`, `workspace_patch`, `workspace_tree`, `workspace_command`, `workspace_rollback` |
| Recipe management | `recipe_list`, `recipe_get`, `recipe_upsert`, `recipe_delete` |
| Tool lifecycle | `tool_inspect`, `tool_refactor`, `tool_retire` |

Synthesized tools live in `<data_dir>/workspace/mcp_servers/hub/hub_server.py`.

## 4. Target Design (ADR-0015)

* **Ingredients** (tool, context source, model profile, runbook) and **recipes** are typed, versioned contracts with a lifecycle status (`draft` → `candidate` → `active` → `deprecated` → `retired`).
* Each ingredient declares a **capability signature** from a controlled vocabulary (verb, resource, scope, effect), plus input/output JSON Schemas.
* Lookup is **Intent → Retrieve → Bind → Adjudicate**: schema-constrained intent extraction, then structured plus semantic retrieval, then schema-validated parameter binding, then a bounded model choice.
* New recipes are earned through verified runs. Real-time crafting creates candidates; nightly curation clusters, promotes, demotes, and merges.

---

## 5. Knowledge Graduation Pipeline

Agent OS enforces continuous, structured knowledge evolution across the 4-folder Wiki structure:

```
[00_Inbox]  ──(Linting & Tag Validation)──>  [01_Notes]  ──(Deprecation)──>  [02_Archive]
```

1. **Inbox Entry**: Notes in `00_Inbox` can be rough drafts or unformatted thoughts.
2. **Graduation Service**:
   * Evaluates notes for valid YAML frontmatter (`title`, `tags`, `created_at`).
   * Validates backlinks and markdown syntax.
   * Resolves file name collisions deterministically (e.g. appending `-1`, `-2` rather than overwriting existing notes).
   * Moves validated notes to `01_Notes`.
