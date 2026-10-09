"""Unit tests for IntentResolver: dual retrieval, schema binding, and adjudication."""

from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.seeding import seed_default_ingredients
from agent_os.domain.ingredients.vocabulary import Scope, Verb
from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.embedding.fastembed_provider import (
    DeterministicMockEmbeddingProvider,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.ingredient_index import IngredientVectorIndex
from agent_os.infrastructure.storage.ingredient_store import SqliteIngredientStore
from agent_os.kernel.intent_resolver import (
    IntentResolver,
    ResolutionVerdict,
)


class MockAdjudicationAdapter(BaseModelAdapter):
    """Mock adapter returning JSON for model adjudication."""

    def __init__(self, selected_id: str) -> None:
        self.selected_id = selected_id

    async def complete(self, request: CompletionRequest):
        payload = f'{{"selected_recipe_id": "{self.selected_id}", "rationale": "best fit"}}'
        yield StreamChunk(delta=payload)


@pytest.fixture
def test_env(tmp_path: Path):
    db_path = tmp_path / "ingredients.db"
    store = SqliteIngredientStore(db_path=db_path)
    index = IngredientVectorIndex(db_path=db_path)
    provider = DeterministicMockEmbeddingProvider(dimension=32)
    seed_default_ingredients(store, index, provider)
    return store, index, provider


def test_dual_retrieval_prioritizes_signature_match(test_env) -> None:
    """Relational signature match outranks semantic-only candidates."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    intent = TaskIntent(
        verb=Verb.LIST,
        resource="workspace.directory",
        scope=Scope.WORKSPACE,
        parameters={"relative_path": "."},
        desired_output="list of entries",
        normalized_utterance="list workspace directories",
    )

    candidates = resolver.retrieve_candidates(intent)
    assert len(candidates) > 0
    # workspace_inspect_directory should be #1 because signature matches
    top = candidates[0]
    assert top.recipe.id == "workspace_inspect_directory"
    assert top.signature_matched is True
    assert top.fusion_score >= 10.0


def test_bind_candidate_enforces_effect_tier(test_env) -> None:
    """Binding drops candidate if recipe effect exceeds allowed tier."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    intent = TaskIntent(
        verb=Verb.WRITE,
        resource="vault.note",
        scope=Scope.VAULT,
        parameters={"note_path": "test.md", "content": "hello"},
        desired_output="note status",
        normalized_utterance="save note to vault",
    )

    candidates = resolver.retrieve_candidates(intent)
    capture_candidate = next((c for c in candidates if c.recipe.id == "wiki_capture_note"), None)
    assert capture_candidate is not None

    # When allowed tier is only READ, wiki_capture_note (STATE_CHANGE) must be dropped
    bound_read_only = resolver.bind_candidate(
        capture_candidate, intent, mounted_tools={"wiki_write"}, allowed_tier=ActionTier.READ
    )
    assert bound_read_only is None

    # When allowed tier is STATE_CHANGE, binding succeeds
    bound_state_change = resolver.bind_candidate(
        capture_candidate,
        intent,
        mounted_tools={"wiki_write"},
        allowed_tier=ActionTier.STATE_CHANGE,
    )
    assert bound_state_change is not None
    assert bound_state_change.bound_parameters["note_path"] == "test.md"


def test_bind_candidate_enforces_mounted_tools(test_env) -> None:
    """Binding drops candidate if required tools are not mounted."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    intent = TaskIntent(
        verb=Verb.AUDIT,
        resource="runtime.health",
        scope=Scope.RUNTIME,
        parameters={},
        desired_output="health report",
        normalized_utterance="how healthy is the system",
    )

    candidates = resolver.retrieve_candidates(intent)
    health_candidate = next((c for c in candidates if c.recipe.id == "self_health_audit"), None)
    assert health_candidate is not None

    # Tool not mounted -> dropped
    bound_unmounted = resolver.bind_candidate(
        health_candidate, intent, mounted_tools={"unrelated_tool"}, allowed_tier=ActionTier.READ
    )
    assert bound_unmounted is None

    # Tool mounted -> bound
    bound_mounted = resolver.bind_candidate(
        health_candidate, intent, mounted_tools={"telemetry_audit"}, allowed_tier=ActionTier.READ
    )
    assert bound_mounted is not None
    # Parameter default was applied
    assert bound_mounted.bound_parameters["hours"] == 24


@pytest.mark.asyncio
async def test_resolve_single_viable_candidate_executes_directly(test_env) -> None:
    """When exactly one viable candidate passes binding, verdict is EXECUTE."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    intent = TaskIntent(
        verb=Verb.READ,
        resource="workspace.file",
        scope=Scope.WORKSPACE,
        parameters={"relative_path": "README.md"},
        desired_output="lines from README",
        normalized_utterance="read the README file",
    )

    result = await resolver.resolve(
        intent,
        mounted_tools={"workspace_read"},
        allowed_tier=ActionTier.READ,
    )

    assert result.verdict == ResolutionVerdict.EXECUTE
    assert result.recipe is not None
    assert result.recipe.id == "workspace_read_file"
    assert result.bound_parameters["relative_path"] == "README.md"
    assert result.bound_parameters["start_line"] == 1
    assert result.bound_parameters["line_count"] == 100


@pytest.mark.asyncio
async def test_resolve_zero_viable_candidates_returns_compose(test_env) -> None:
    """When no recipe matches or binds, verdict is COMPOSE."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    intent = TaskIntent(
        verb=Verb.DELETE,
        resource="workspace.file",
        scope=Scope.WORKSPACE,
        parameters={"relative_path": "tmp.txt"},
        desired_output="deleted file",
        normalized_utterance="nuke tmp.txt",
    )

    result = await resolver.resolve(
        intent,
        mounted_tools={"workspace_read", "workspace_write"},
        allowed_tier=ActionTier.DESTRUCTIVE,
    )

    assert result.verdict == ResolutionVerdict.COMPOSE
    assert result.recipe is None


@pytest.mark.asyncio
async def test_resolve_multiple_candidates_adjudication(test_env) -> None:
    """When 2+ candidates bind, model adjudication chooses the recipe."""
    store, index, provider = test_env
    adapter = MockAdjudicationAdapter(selected_id="workspace_inspect_directory")
    resolver = IntentResolver(store, index, provider, model_adapter=adapter)

    intent = TaskIntent(
        verb=Verb.LIST,
        resource="workspace.directory",
        scope=Scope.WORKSPACE,
        parameters={"relative_path": "."},
        desired_output="directory items",
        normalized_utterance="show workspace files and directories",
    )

    result = await resolver.resolve(
        intent,
        mounted_tools={"workspace_tree"},
        allowed_tier=ActionTier.READ,
    )

    assert result.verdict == ResolutionVerdict.EXECUTE
    assert result.recipe is not None
    assert result.recipe.id == "workspace_inspect_directory"


@pytest.mark.asyncio
async def test_paraphrased_queries_resolve_to_same_recipe(test_env) -> None:
    """Different phrasings with same intent resolve consistently."""
    store, index, provider = test_env
    resolver = IntentResolver(store, index, provider)

    phrasings = [
        "what's inside my workspace folder",
        "list the files in the workspace",
        "show me workspace directories",
    ]

    for utterance in phrasings:
        intent = TaskIntent(
            verb=Verb.LIST,
            resource="workspace.directory",
            scope=Scope.WORKSPACE,
            parameters={"relative_path": "."},
            desired_output="list of entries",
            normalized_utterance=utterance,
        )
        res = await resolver.resolve(
            intent,
            mounted_tools={"workspace_tree"},
            allowed_tier=ActionTier.READ,
        )
        assert res.verdict == ResolutionVerdict.EXECUTE
        assert res.recipe is not None
        assert res.recipe.id == "workspace_inspect_directory"
