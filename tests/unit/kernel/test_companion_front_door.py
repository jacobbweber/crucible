"""Unit tests for the Companion Front Door and fulfill_request tool call (Phase 22)."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.gateway import CompletionRequest, StreamChunk, ToolCallPart
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.seeding import seed_default_ingredients
from agent_os.domain.ingredients.vocabulary import (
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)
from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.embedding.fastembed_provider import (
    DeterministicMockEmbeddingProvider,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.structured import StructuredOutputError
from agent_os.infrastructure.storage.ingredient_index import IngredientVectorIndex
from agent_os.infrastructure.storage.ingredient_store import SqliteIngredientStore
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.companion_front_door import (
    build_fulfill_request_tool_spec,
    parse_task_intent,
)
from agent_os.kernel.intent_resolver import IntentResolver, ResolutionVerdict


class CapturingModelAdapter(BaseModelAdapter):
    """Hermetic model adapter capturing CompletionRequest and streaming canned chunks."""

    def __init__(self, chunks: list[StreamChunk]) -> None:
        self.chunks = chunks
        self.captured_requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest):
        self.captured_requests.append(request)
        for chunk in self.chunks:
            yield chunk


def test_build_fulfill_request_tool_spec_is_self_contained() -> None:
    """Tool schema must be self-contained without $defs or $ref (Finding G4)."""
    registry = ResourceVocabularyRegistry.default_registry()
    spec = build_fulfill_request_tool_spec(registry)

    assert spec.name == "fulfill_request"
    params = spec.parameters
    assert "$defs" not in params
    assert "$ref" not in str(params)

    props = params["properties"]
    assert "verb" in props
    assert "resource" in props
    assert "scope" in props
    assert "parameters" in props
    assert "desired_output" in props
    assert "normalized_utterance" in props

    # Check enums contain vocabulary values
    assert set(props["verb"]["enum"]) == {v.value for v in Verb}
    assert set(props["scope"]["enum"]) == {s.value for s in Scope}
    assert set(props["resource"]["enum"]) == set(registry.get_descriptions().keys())

    # Check that descriptions include per-value explanations (Finding G7)
    assert "inspect or retrieve data" in props["verb"]["description"].lower()
    assert "filesystem.directory" in props["resource"]["description"]
    assert "workspace directory" in props["scope"]["description"].lower()


def test_parse_task_intent_valid() -> None:
    """Valid ToolCallPart parses into TaskIntent and derives CapabilitySignature."""
    call = ToolCallPart(
        id="c1",
        name="fulfill_request",
        arguments=json.dumps(
            {
                "verb": "list",
                "resource": "workspace.directory",
                "scope": "workspace",
                "parameters": {"relative_path": "."},
                "desired_output": "list of files and folders",
                "normalized_utterance": "list files in workspace",
            }
        ),
    )

    intent = parse_task_intent(call)
    assert intent.verb == Verb.LIST
    assert intent.resource == "workspace.directory"
    assert intent.scope == Scope.WORKSPACE
    assert intent.parameters == {"relative_path": "."}
    assert intent.normalized_utterance == "list files in workspace"

    sig = intent.to_capability_signature(Effect=None) if False else intent.to_capability_signature()
    assert sig.verb == Verb.LIST
    assert sig.resource == "workspace.directory"


def test_parse_task_intent_invalid_raises_structured_output_error() -> None:
    """Missing or invalid fields raise StructuredOutputError."""
    call = ToolCallPart(
        id="c2",
        name="fulfill_request",
        arguments='{"verb": "invalid_verb", "resource": "something"}',
    )
    with pytest.raises(StructuredOutputError):
        parse_task_intent(call)


@pytest.mark.asyncio
async def test_companion_offers_fulfill_request_tool(tmp_path: Path) -> None:
    """CompanionChatLoop offers fulfill_request with auto tool_choice and no regex instructions."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Spec Test")

    adapter = CapturingModelAdapter(
        [StreamChunk(delta="Hello! How can I help you?", finish_reason="stop")]
    )
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=CompanionConfig(name="Astra"),
    )

    async for _ in loop.execute_turn("Hello"):
        pass

    assert len(adapter.captured_requests) == 1
    req = adapter.captured_requests[0]
    assert len(req.tools) >= 1
    tool_names = [t.name for t in req.tools]
    assert "fulfill_request" in tool_names
    assert req.tool_choice == "auto"

    # Verify system prompt has no [DISPATCH:] directives
    sys_msg = next((m.content for m in req.messages if m.role == "system"), "")
    assert "[DISPATCH:" not in sys_msg
    assert "fulfill_request" in sys_msg
    assert "DO NOT call 'fulfill_request'" in sys_msg


@pytest.mark.asyncio
async def test_front_door_to_intent_resolver_handshake(tmp_path: Path) -> None:
    """End-to-end handshake: front door captures TaskIntent and resolves to verified recipe."""
    db_path = tmp_path / "ingredients.db"
    store = SqliteIngredientStore(db_path=db_path)
    index = IngredientVectorIndex(db_path=db_path)
    provider = DeterministicMockEmbeddingProvider(dimension=32)
    seed_default_ingredients(store, index, provider)

    resolver = IntentResolver(store, index, provider)
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Handshake Test")

    intent_payload = {
        "verb": "list",
        "resource": "workspace.directory",
        "scope": "workspace",
        "parameters": {"relative_path": "."},
        "desired_output": "list of directory entries",
        "normalized_utterance": "show workspace directories",
    }
    chunks = [
        StreamChunk(delta="Checking the workspace for you. ", finish_reason=None),
        StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_hs",
                    name="fulfill_request",
                    arguments=json.dumps(intent_payload),
                )
            ],
        ),
    ]

    captured_intent: TaskIntent | None = None

    async def mock_dispatcher(session_id: str, task: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal captured_intent
        captured_intent = kwargs.get("intent")
        # Direct resolver execution with captured intent
        res = await resolver.resolve(
            captured_intent,  # type: ignore[arg-type]
            mounted_tools={"workspace_tree"},
            allowed_tier=ActionTier.READ,
        )
        return {"resolution": res, "status": "completed"}

    adapter = CapturingModelAdapter(chunks)
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=CompanionConfig(name="Astra"),
        job_dispatcher=mock_dispatcher,  # type: ignore[arg-type]
    )

    events: list[StreamTurnEvent] = []
    async for ev in loop.execute_turn("Show me the workspace directory"):
        events.append(ev)

    assert captured_intent is not None
    assert captured_intent.verb == Verb.LIST
    assert captured_intent.resource == "workspace.directory"

    dispatched = [e for e in events if e.event_type == "job_dispatched"]
    assert len(dispatched) == 1
    res = dispatched[0].dispatched_job["resolution"]
    assert res.verdict == ResolutionVerdict.EXECUTE
    assert res.recipe is not None
    assert res.recipe.id == "workspace_inspect_directory"
