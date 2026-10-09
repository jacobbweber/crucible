"""Unit tests for ingredient contracts, envelope hashing, and hard crafting rules."""

import pytest

from agent_os.domain.ingredients.builtin import get_builtin_tool_contracts
from agent_os.domain.ingredients.contracts import (
    AcceptanceCheck,
    AcceptanceCheckType,
    ContractExample,
    RecipeContract,
    ToolContract,
)
from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientKind,
    IngredientStatus,
    compute_sha256,
)
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.rules import (
    CraftingRuleViolation,
    validate_canonical_id,
    validate_effect_alignment,
    validate_recipe_contract,
    validate_tool_contract,
)
from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import (
    Effect,
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)
from agent_os.domain.policy import ActionTier


def _sample_tool_contract(tool_id: str = "read_file") -> ToolContract:
    return ToolContract(
        id=tool_id,
        version=1,
        kind=IngredientKind.TOOL,
        status=IngredientStatus.ACTIVE,
        description="Read file contents",
        capability=CapabilitySignature(
            verb=Verb.READ,
            resource="filesystem.file",
            scope=Scope.HOST,
            effect=Effect.READ_ONLY,
        ),
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {"content": {"type": "string"}},
        },
        examples=[
            ContractExample(input={"path": "test.txt"}, description="Read test.txt"),
        ],
    )


def test_canonical_id_validation_rejects_forbidden_prefixes() -> None:
    """Rule 8: Alias prefixes like mcp_hub_ and warehouse_ are strictly forbidden."""
    validate_canonical_id("valid_tool_name")
    validate_canonical_id("workspace-read-1")

    with pytest.raises(CraftingRuleViolation, match="forbidden alias prefix 'mcp_hub_'"):
        validate_canonical_id("mcp_hub_tool")

    with pytest.raises(CraftingRuleViolation, match="forbidden alias prefix 'warehouse_'"):
        validate_canonical_id("warehouse_note")

    with pytest.raises(CraftingRuleViolation, match="pattern"):
        validate_canonical_id("invalid tool id with spaces")


def test_tool_contract_content_hash_auto_generation() -> None:
    """Tool contracts auto-compute a deterministic content hash."""
    t1 = _sample_tool_contract("tool_a")
    assert len(t1.content_hash) == 64
    assert t1.content_hash == compute_sha256(
        {
            "id": "tool_a",
            "version": 1,
            "capability": "read:filesystem.file@host[read_only]",
            "input_schema": t1.input_schema,
            "output_schema": t1.output_schema,
            "runtime": "builtin",
        }
    )


def test_tool_contract_rule2_rejects_non_object_schema() -> None:
    """Rule 2: Tools must declare typed JSON schemas of type 'object'."""
    with pytest.raises(ValueError, match="input_schema of type 'object' must define 'properties'"):
        ToolContract(
            id="bad_tool",
            kind=IngredientKind.TOOL,
            description="Bad schema tool",
            capability=CapabilitySignature(
                verb=Verb.READ,
                resource="filesystem.file",
                scope=Scope.HOST,
                effect=Effect.READ_ONLY,
            ),
            input_schema={"type": "object"},  # missing properties
            output_schema={"type": "object", "properties": {}},
            examples=[ContractExample(input={})],
        )


def test_tool_contract_rule3_requires_examples_and_validates_inputs() -> None:
    """Rule 3: Tools must provide at least 1 example whose input matches input_schema."""
    with pytest.raises(ValueError, match="at least 1"):
        ToolContract(
            id="no_examples",
            kind=IngredientKind.TOOL,
            description="Tool without examples",
            capability=CapabilitySignature(
                verb=Verb.READ,
                resource="filesystem.file",
                scope=Scope.HOST,
                effect=Effect.READ_ONLY,
            ),
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "object", "properties": {}},
            examples=[],  # violated
        )

    # Tool with example that violates schema
    tool_invalid_example = ToolContract(
        id="mismatched_example",
        kind=IngredientKind.TOOL,
        description="Mismatched example",
        capability=CapabilitySignature(
            verb=Verb.READ,
            resource="filesystem.file",
            scope=Scope.HOST,
            effect=Effect.READ_ONLY,
        ),
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
        output_schema={"type": "object", "properties": {}},
        examples=[ContractExample(input={"count": "not an int"})],
    )
    with pytest.raises(CraftingRuleViolation, match="failed input_schema validation"):
        validate_tool_contract(tool_invalid_example)


def test_recipe_contract_validation_and_resolver() -> None:
    """Rule 5: Recipe references must resolve to candidate or active ingredients."""
    tool = _sample_tool_contract("tool_a")
    reg = ResourceVocabularyRegistry(seed_defaults=True)

    recipe = RecipeContract(
        id="inspect_file_recipe",
        version=1,
        kind=IngredientKind.RECIPE,
        status=IngredientStatus.CANDIDATE,
        description="Inspect a file on disk",
        capability=CapabilitySignature(
            verb=Verb.READ,
            resource="filesystem.file",
            scope=Scope.HOST,
            effect=Effect.READ_ONLY,
        ),
        inputs_schema={
            "type": "object",
            "properties": {"target_path": {"type": "string"}},
            "required": ["target_path"],
        },
        outputs_schema={
            "type": "object",
            "properties": {"file_content": {"type": "string"}},
        },
        tools=["tool_a@1"],
        acceptance=[
            AcceptanceCheck(
                check_type=AcceptanceCheckType.JSON_SCHEMA,
                rule="outputs.file_content is not empty",
            )
        ],
        intent_examples=["read test.txt", "show me what's inside file.log"],
    )

    # Valid resolver mapping tool_a@1 to tool
    def valid_resolver(ref_id: str, version: int) -> IngredientEnvelope | None:
        if ref_id == "tool_a" and version == 1:
            return tool
        return None

    validate_recipe_contract(recipe, resolver=valid_resolver, registry=reg)

    # Missing ref raises violation
    def missing_resolver(ref_id: str, version: int) -> IngredientEnvelope | None:
        return None

    with pytest.raises(CraftingRuleViolation, match="references non-existent ingredient"):
        validate_recipe_contract(recipe, resolver=missing_resolver, registry=reg)


def test_effect_alignment_rule6() -> None:
    """Rule 6: Declared effect cannot exceed permitted action tier."""
    # READ_ONLY allows READ, STATE_CHANGE, DESTRUCTIVE
    assert validate_effect_alignment(Effect.READ_ONLY, ActionTier.READ)
    assert validate_effect_alignment(Effect.READ_ONLY, ActionTier.STATE_CHANGE)
    assert validate_effect_alignment(Effect.READ_ONLY, ActionTier.DESTRUCTIVE)

    # STATE_CHANGE requires at least STATE_CHANGE
    assert not validate_effect_alignment(Effect.STATE_CHANGE, ActionTier.READ)
    assert validate_effect_alignment(Effect.STATE_CHANGE, ActionTier.STATE_CHANGE)
    assert validate_effect_alignment(Effect.STATE_CHANGE, ActionTier.DESTRUCTIVE)

    # DESTRUCTIVE requires DESTRUCTIVE
    assert not validate_effect_alignment(Effect.DESTRUCTIVE, ActionTier.READ)
    assert not validate_effect_alignment(Effect.DESTRUCTIVE, ActionTier.STATE_CHANGE)
    assert validate_effect_alignment(Effect.DESTRUCTIVE, ActionTier.DESTRUCTIVE)


def test_task_intent_conversion() -> None:
    """TaskIntent converts to CapabilitySignature."""
    intent = TaskIntent(
        verb=Verb.LIST,
        resource="workspace.directory",
        scope=Scope.WORKSPACE,
        parameters={"relative_path": "src"},
        desired_output="list of files",
        normalized_utterance="show files in src",
    )
    sig = intent.to_capability_signature(Effect.READ_ONLY)
    assert sig.verb == Verb.LIST
    assert sig.resource == "workspace.directory"
    assert sig.scope == Scope.WORKSPACE
    assert sig.effect == Effect.READ_ONLY


def test_all_builtin_tool_contracts_are_valid() -> None:
    """Every built-in tool contract must satisfy all crafting rules and registry checks."""
    builtins = get_builtin_tool_contracts()
    assert len(builtins) >= 8

    reg = ResourceVocabularyRegistry.default_registry()
    for tool in builtins:
        validate_tool_contract(tool, registry=reg)
        assert tool.status == IngredientStatus.ACTIVE
        assert len(tool.examples) >= 1
