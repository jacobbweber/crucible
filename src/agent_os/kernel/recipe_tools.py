"""Recipe management tools allowing agents to inspect, author, and curate execution playbooks."""

import json
from datetime import UTC, datetime
from typing import Any

from agent_os.domain.policy import ActionTier
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository


def _p(name: str, type_name: str, desc: str, req: bool = True, default: Any = None) -> ToolParameterSchema:
    return ToolParameterSchema(name=name, type_name=type_name, description=desc, required=req, default=default)


class RecipeToolSuite:
    """Tool suite providing agent access to recipe playbook inspection, authoring, and curation."""

    def __init__(self, recipe_repo: RecipeRepository) -> None:
        self.recipe_repo = recipe_repo

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions and schemas for recipe operations."""
        return [
            ToolDefinition(
                name="recipe_list",
                description="List available recipe playbooks, optionally filtering by semantic tag.",
                action_tier=ActionTier.READ,
                parameters=[
                    _p("tag", "string", "Optional tag to filter recipes (e.g. 'filesystem', 'research').", False, ""),
                ],
            ),
            ToolDefinition(
                name="recipe_get",
                description="Retrieve full details, required tools, and runbook instructions for a recipe by ID.",
                action_tier=ActionTier.READ,
                parameters=[
                    _p("recipe_id", "string", "Unique identifier of the recipe (e.g. 'host_filesystem_inspection')."),
                ],
            ),
            ToolDefinition(
                name="recipe_upsert",
                description="Create or update a declarative recipe playbook with ingredients and runbook.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    _p("recipe_id", "string", "Unique identifier for the recipe."),
                    _p("name", "string", "Human-readable name of the playbook."),
                    _p("description", "string", "Detailed operational description and purpose of the recipe."),
                    _p("required_tools", "string", "Comma-separated list of required tool names (e.g. 'list_drive_contents')."),
                    _p("tags", "string", "Comma-separated semantic intent tags (e.g. 'filesystem,drive,list')."),
                    _p("body", "string", "Runbook instructions, operational steps, or verification criteria.", False, ""),
                    _p("execution_engine", "string", "Execution engine ('react', 'stategraph', 'pev').", False, "react"),
                    _p("target_model_tier", "string", "Model tier ('fast', 'reasoning', 'coding').", False, "fast"),
                    _p("timeout_seconds", "integer", "Timeout in seconds.", False, 60),
                ],
            ),
            ToolDefinition(
                name="recipe_delete",
                description="Delete a recipe playbook from the persistent recipe library.",
                action_tier=ActionTier.DESTRUCTIVE,
                parameters=[
                    _p("recipe_id", "string", "Unique identifier of the recipe to delete."),
                ],
            ),
        ]

    def recipe_list(self, tag: str = "") -> ToolExecutionResult:
        """List recipes from SQLite repository."""
        try:
            records = self.recipe_repo.list_recipes()
            filter_tag = tag.strip().lower()
            if filter_tag:
                records = [r for r in records if any(filter_tag in t.lower() for t in r.metadata.tags)]

            if not records:
                msg = f"No recipes found matching tag '{tag}'." if tag else "No recipes found in library."
                return ToolExecutionResult(tool_name="recipe_list", success=True, output=msg)

            lines = [f"Found {len(records)} recipe playbook(s):"]
            for r in records:
                tools_str = ", ".join(r.metadata.required_tools) or "None"
                tags_str = ", ".join(r.metadata.tags)
                lines.append(
                    f"- `{r.metadata.recipe_id}`: {r.metadata.name} | Engine: {r.metadata.execution_engine} "
                    f"| Tools: [{tools_str}] | Tags: [{tags_str}]"
                )
            return ToolExecutionResult(tool_name="recipe_list", success=True, output="\n".join(lines))
        except Exception as exc:
            return ToolExecutionResult(tool_name="recipe_list", success=False, output="", error=str(exc))

    def recipe_get(self, recipe_id: str) -> ToolExecutionResult:
        """Get recipe details by ID."""
        try:
            r = self.recipe_repo.get_recipe(recipe_id)
            if not r:
                return ToolExecutionResult(
                    tool_name="recipe_get", success=False, output="", error=f"Recipe '{recipe_id}' not found."
                )

            data = {
                "recipe_id": r.metadata.recipe_id,
                "name": r.metadata.name,
                "description": r.metadata.description,
                "execution_engine": r.metadata.execution_engine,
                "target_model_tier": r.metadata.target_model_tier,
                "required_tools": r.metadata.required_tools,
                "tags": r.metadata.tags,
                "timeout_seconds": r.metadata.timeout_seconds,
                "body": r.body,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            return ToolExecutionResult(
                tool_name="recipe_get", success=True, output=json.dumps(data, indent=2)
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="recipe_get", success=False, output="", error=str(exc))

    def recipe_upsert(
        self,
        recipe_id: str,
        name: str,
        description: str,
        required_tools: str,
        tags: str,
        body: str = "",
        execution_engine: str = "react",
        target_model_tier: str = "fast",
        timeout_seconds: int = 60,
    ) -> ToolExecutionResult:
        """Create or update a recipe record."""
        try:
            t_list = [t.strip() for t in required_tools.split(",") if t.strip()]
            tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
            tier = target_model_tier.strip().lower()
            if tier in ("fast_local", "fast"):
                resolved_tier = "fast"
            elif tier in ("reasoning", "reason"):
                resolved_tier = "reasoning"
            elif tier in ("coding", "code"):
                resolved_tier = "coding"
            else:
                resolved_tier = "fast"

            meta = RecipeMetadata(
                recipe_id=recipe_id.strip(),
                name=name.strip(),
                description=description.strip(),
                execution_engine=execution_engine.strip(),  # type: ignore[arg-type]
                target_model_tier=resolved_tier,  # type: ignore[arg-type]
                tags=tag_list,
                required_tools=t_list,
                timeout_seconds=int(timeout_seconds),
            )
            now = datetime.now(UTC)
            record = RecipeRecord(
                metadata=meta,
                markdown_path=f"recipes/{recipe_id.strip()}.md",
                body=body.strip(),
                created_at=now,
                updated_at=now,
            )
            self.recipe_repo.upsert_recipe(record)
            return ToolExecutionResult(
                tool_name="recipe_upsert",
                success=True,
                output=f"Recipe '{recipe_id}' saved successfully with {len(t_list)} tools and {len(tag_list)} tags.",
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="recipe_upsert", success=False, output="", error=str(exc))

    def recipe_delete(self, recipe_id: str) -> ToolExecutionResult:
        """Delete recipe by ID."""
        try:
            ok = self.recipe_repo.delete_recipe(recipe_id)
            if ok:
                return ToolExecutionResult(
                    tool_name="recipe_delete", success=True, output=f"Recipe '{recipe_id}' deleted successfully."
                )
            return ToolExecutionResult(
                tool_name="recipe_delete", success=False, output="", error=f"Recipe '{recipe_id}' not found."
            )
        except Exception as exc:
            return ToolExecutionResult(tool_name="recipe_delete", success=False, output="", error=str(exc))
