"""Hard crafting rules and validation functions enforced on ingredient creation and writes."""

import re
from collections.abc import Callable
from typing import Any

import jsonschema
from jsonschema.exceptions import SchemaError

from agent_os.domain.ingredients.contracts import RecipeContract, ToolContract
from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientStatus,
)
from agent_os.domain.ingredients.vocabulary import (
    Effect,
    ResourceVocabularyRegistry,
)
from agent_os.domain.policy import ActionTier

_FORBIDDEN_PREFIXES = ("mcp_hub_", "warehouse_")
_CANONICAL_ID_RE = re.compile(r"^[a-z0-9_-]+$")

_EFFECT_SEVERITY: dict[Effect, int] = {
    Effect.READ_ONLY: 0,
    Effect.STATE_CHANGE: 1,
    Effect.DESTRUCTIVE: 2,
}

_TIER_SEVERITY: dict[ActionTier, int] = {
    ActionTier.READ: 0,
    ActionTier.STATE_CHANGE: 1,
    ActionTier.DESTRUCTIVE: 2,
}


class CraftingRuleViolation(ValueError):
    """Raised when an ingredient violates hard crafting constraints."""


def validate_canonical_id(id_str: str) -> None:
    """Rule 8: Ensure ingredient ID is canonical without alias prefixes."""
    if not _CANONICAL_ID_RE.match(id_str):
        raise CraftingRuleViolation(f"Ingredient ID '{id_str}' must match pattern '^[a-z0-9_-]+$'.")
    for prefix in _FORBIDDEN_PREFIXES:
        if id_str.startswith(prefix):
            raise CraftingRuleViolation(
                f"Ingredient ID '{id_str}' contains forbidden alias prefix '{prefix}'."
            )


def validate_schema_structure(schema: dict[str, Any], context_label: str) -> None:
    """Validate that a dict represents a valid JSON Schema object."""
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except SchemaError as err:
        raise CraftingRuleViolation(
            f"Invalid JSON Schema for {context_label}: {err.message}"
        ) from err


def validate_tool_contract(
    tool: ToolContract,
    registry: ResourceVocabularyRegistry | None = None,
) -> None:
    """Enforce Rules 1, 2, 3, 8 for a ToolContract."""
    validate_canonical_id(tool.id)

    # Rule 2: Valid typed JSON Schema, no blanket untyped string
    validate_schema_structure(tool.input_schema, f"tool '{tool.id}' input_schema")
    validate_schema_structure(tool.output_schema, f"tool '{tool.id}' output_schema")

    if tool.input_schema.get("type") != "object":
        actual_type = tool.input_schema.get("type")
        raise CraftingRuleViolation(
            f"Tool '{tool.id}' input_schema type must be 'object', got '{actual_type}'."
        )

    # Check resource is known
    if registry and not registry.is_valid(tool.capability.resource):
        raise CraftingRuleViolation(
            f"Tool '{tool.id}' references unregistered resource '{tool.capability.resource}'."
        )

    # Rule 3: At least one contract example, and inputs must satisfy input_schema
    if not tool.examples:
        raise CraftingRuleViolation(f"Tool '{tool.id}' must provide at least one contract example.")

    validator = jsonschema.Draft202012Validator(tool.input_schema)
    for i, ex in enumerate(tool.examples):
        errors = list(validator.iter_errors(ex.input))
        if errors:
            first_err = errors[0].message
            raise CraftingRuleViolation(
                f"Tool '{tool.id}' example {i} failed input_schema validation: {first_err}"
            )


def validate_recipe_contract(
    recipe: RecipeContract,
    resolver: Callable[[str, int], IngredientEnvelope | None] | None = None,
    registry: ResourceVocabularyRegistry | None = None,
) -> None:
    """Enforce Rules 4, 5, 8 for a RecipeContract."""
    validate_canonical_id(recipe.id)

    validate_schema_structure(recipe.inputs_schema, f"recipe '{recipe.id}' inputs_schema")
    validate_schema_structure(recipe.outputs_schema, f"recipe '{recipe.id}' outputs_schema")

    # Rule 4: Inputs schema must be an object
    if recipe.inputs_schema.get("type") != "object":
        raise CraftingRuleViolation(f"Recipe '{recipe.id}' inputs_schema type must be 'object'.")

    if registry and not registry.is_valid(recipe.capability.resource):
        raise CraftingRuleViolation(
            f"Recipe '{recipe.id}' references unregistered resource '{recipe.capability.resource}'."
        )

    # Rule 5: Recipe references must resolve to candidate or active ingredients at pinned version
    if resolver is not None:
        all_refs = list(recipe.tools) + list(recipe.context_sources)
        if recipe.model_profile:
            all_refs.append(recipe.model_profile)
        if recipe.runbook:
            all_refs.append(recipe.runbook)

        for ref in all_refs:
            ref_id, version = IngredientEnvelope.parse_pinned_ref(ref)
            target = resolver(ref_id, version)
            if target is None:
                raise CraftingRuleViolation(
                    f"Recipe '{recipe.id}' references non-existent ingredient '{ref}'."
                )
            if target.status not in (IngredientStatus.CANDIDATE, IngredientStatus.ACTIVE):
                raise CraftingRuleViolation(
                    f"Recipe '{recipe.id}' references ingredient '{ref}' with unusable "
                    f"status '{target.status.value}' (must be candidate or active)."
                )


def validate_effect_alignment(declared: Effect, allowed_tier: ActionTier) -> bool:
    """Rule 6: Verify declared effect does not exceed allowed policy tier."""
    declared_sev = _EFFECT_SEVERITY[declared]
    allowed_sev = _TIER_SEVERITY[allowed_tier]
    return declared_sev <= allowed_sev
