"""Unit tests for SqliteIngredientStore, versioned queries, and capability signatures."""

from pathlib import Path

import pytest

from agent_os.domain.ingredients.builtin import get_builtin_tool_contracts
from agent_os.domain.ingredients.contracts import (
    ContextSourceContract,
    ContextSourceKind,
    ContractExample,
    ModelProfile,
    RunbookContract,
    RunbookEngine,
    RunbookStep,
    ThinkingLevel,
    ToolContract,
)
from agent_os.domain.ingredients.envelope import (
    IngredientKind,
    IngredientStatus,
)
from agent_os.domain.ingredients.rules import CraftingRuleViolation
from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import (
    Effect,
    Scope,
    Verb,
)
from agent_os.infrastructure.storage.ingredient_store import SqliteIngredientStore


@pytest.fixture
def temp_store(tmp_path: Path) -> SqliteIngredientStore:
    db_path = tmp_path / "ingredients.db"
    return SqliteIngredientStore(db_path=db_path)


def test_store_saves_and_retrieves_polymorphic_ingredients(
    temp_store: SqliteIngredientStore,
) -> None:
    """Store persists and correctly deserializes all ingredient contract types."""
    # 1. Tool
    tool = ToolContract(
        id="test_read_file",
        version=1,
        kind=IngredientKind.TOOL,
        status=IngredientStatus.ACTIVE,
        description="Read file",
        capability=CapabilitySignature(
            verb=Verb.READ,
            resource="filesystem.file",
            scope=Scope.HOST,
            effect=Effect.READ_ONLY,
        ),
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"content": {"type": "string"}}},
        examples=[ContractExample(input={"path": "a.txt"})],
    )
    temp_store.save(tool)
    fetched_tool = temp_store.get("test_read_file", 1)
    assert isinstance(fetched_tool, ToolContract)
    assert fetched_tool.id == "test_read_file"
    assert fetched_tool.capability.verb == Verb.READ

    # 2. Context source
    ctx = ContextSourceContract(
        id="session_context",
        version=1,
        kind=IngredientKind.CONTEXT_SOURCE,
        status=IngredientStatus.ACTIVE,
        description="Session turn history",
        source=ContextSourceKind.SESSION_HISTORY,
        query="last 5 turns",
    )
    temp_store.save(ctx)
    fetched_ctx = temp_store.get("session_context")
    assert isinstance(fetched_ctx, ContextSourceContract)
    assert fetched_ctx.source == ContextSourceKind.SESSION_HISTORY

    # 3. Model profile
    model = ModelProfile(
        id="fast_worker",
        version=1,
        kind=IngredientKind.MODEL_PROFILE,
        status=IngredientStatus.ACTIVE,
        description="Fast reasoning profile",
        role="worker",
        thinking_level=ThinkingLevel.LOW,
        max_tokens=1024,
    )
    temp_store.save(model)
    fetched_model = temp_store.get("fast_worker")
    assert isinstance(fetched_model, ModelProfile)
    assert fetched_model.thinking_level == ThinkingLevel.LOW

    # 4. Runbook
    runbook = RunbookContract(
        id="file_read_runbook",
        version=1,
        kind=IngredientKind.RUNBOOK,
        status=IngredientStatus.ACTIVE,
        description="Single step file read",
        engine=RunbookEngine.DIRECT,
        steps=[
            RunbookStep(
                step_id="step1",
                tool_ref="test_read_file@1",
                input_bindings={"path": "input.path"},
            )
        ],
    )
    temp_store.save(runbook)
    fetched_runbook = temp_store.get("file_read_runbook")
    assert isinstance(fetched_runbook, RunbookContract)
    assert len(fetched_runbook.steps) == 1


def test_store_versioning_and_latest_lookup(
    temp_store: SqliteIngredientStore,
) -> None:
    """Store tracks multiple versions and resolves None version to latest."""
    t1 = ToolContract(
        id="custom_scanner",
        version=1,
        kind=IngredientKind.TOOL,
        status=IngredientStatus.ACTIVE,
        description="Scanner v1",
        capability=CapabilitySignature(
            verb=Verb.AUDIT,
            resource="runtime.health",
            scope=Scope.RUNTIME,
            effect=Effect.READ_ONLY,
        ),
        input_schema={"type": "object", "properties": {"v": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {}},
        examples=[ContractExample(input={"v": 1})],
    )
    t2 = ToolContract(
        id="custom_scanner",
        version=2,
        kind=IngredientKind.TOOL,
        status=IngredientStatus.ACTIVE,
        description="Scanner v2 improved",
        capability=CapabilitySignature(
            verb=Verb.AUDIT,
            resource="runtime.health",
            scope=Scope.RUNTIME,
            effect=Effect.READ_ONLY,
        ),
        input_schema={"type": "object", "properties": {"v": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {}},
        examples=[ContractExample(input={"v": 2})],
    )
    temp_store.save(t1)
    temp_store.save(t2)

    # Latest
    latest = temp_store.get("custom_scanner")
    assert latest is not None
    assert latest.version == 2
    assert latest.description == "Scanner v2 improved"

    # Pinned v1
    v1 = temp_store.get("custom_scanner", 1)
    assert v1 is not None
    assert v1.version == 1
    assert v1.description == "Scanner v1"


def test_store_find_by_signature(temp_store: SqliteIngredientStore) -> None:
    """find_by_signature indexes and matches active/candidate items."""
    for tool in get_builtin_tool_contracts():
        temp_store.save(tool)

    matches = temp_store.find_by_signature(
        verb=Verb.LIST,
        resource="workspace.directory",
        scope=Scope.WORKSPACE,
    )
    assert len(matches) == 1
    assert matches[0].id == "workspace_tree"


def test_store_enforces_rules_on_save(temp_store: SqliteIngredientStore) -> None:
    """Saving an ingredient with invalid canonical ID is rejected."""
    bad_tool = ToolContract(
        id="mcp_hub_bad_tool",
        version=1,
        kind=IngredientKind.TOOL,
        description="Illegal prefix",
        capability=CapabilitySignature(
            verb=Verb.READ,
            resource="filesystem.file",
            scope=Scope.HOST,
            effect=Effect.READ_ONLY,
        ),
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        examples=[ContractExample(input={})],
    )
    with pytest.raises(CraftingRuleViolation, match="forbidden alias prefix"):
        temp_store.save(bad_tool)
