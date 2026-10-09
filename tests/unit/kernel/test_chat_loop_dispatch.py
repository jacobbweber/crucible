import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.gateway import CompletionRequest, StreamChunk, ToolCallPart
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.vocabulary import Scope, Verb
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.chat_loop import (
    CompanionChatLoop,
    extract_dispatch_directives,
    extract_tool_directives,
)


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter yielding pre-configured stream chunks."""

    def __init__(self, chunks: list[StreamChunk]) -> None:
        self.chunks = chunks

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        for chunk in self.chunks:
            yield chunk


def test_extract_directives_parsing() -> None:
    """Verify regex and bracket balancing for dispatch and tool directives."""
    text = (
        "Understood. Starting background tasks:\n"
        "[DISPATCH: Index all inbox notes for graduation]\n"
        '[TOOL: wiki_write {"path": "01_Notes/test.md", "tags": ["ai", "local"]}]\n'
    )
    dispatches = extract_dispatch_directives(text)
    assert dispatches == ["Index all inbox notes for graduation"]

    tools = extract_tool_directives(text)
    assert len(tools) == 1
    tool_name, params = tools[0]
    assert tool_name == "wiki_write"
    assert params == {"path": "01_Notes/test.md", "tags": ["ai", "local"]}


@pytest.mark.asyncio
async def test_chat_loop_dispatches_subjob(tmp_path: Path) -> None:
    """Verify fulfill_request tool call triggers job_dispatcher and yields job_dispatched event."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Dispatch Test")

    intent = TaskIntent(
        verb=Verb.SEARCH,
        resource="vault.note",
        scope=Scope.VAULT,
        parameters={"query": "machine learning"},
        desired_output="matching notes",
        normalized_utterance="Search notes for machine learning",
    )
    chunks = [
        StreamChunk(delta="Working on your request. ", finish_reason=None),
        StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_1",
                    name="fulfill_request",
                    arguments=intent.model_dump_json(),
                )
            ],
        ),
    ]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra")

    dispatched_calls: list[tuple[str, str]] = []

    async def mock_job_dispatcher(session_id: str, task: str) -> dict[str, str]:
        dispatched_calls.append((session_id, task))
        return {"job_id": "job-101", "task": task, "status": "completed"}

    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        job_dispatcher=mock_job_dispatcher,  # type: ignore[arg-type]
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Please search my notes"):
        events.append(event)

    assert len(dispatched_calls) == 1
    assert dispatched_calls[0] == (session.session_id, "Search notes for machine learning")

    dispatched_events = [e for e in events if e.event_type == "job_dispatched"]
    assert len(dispatched_events) == 1
    assert dispatched_events[0].dispatched_job == {
        "job_id": "job-101",
        "task": "Search notes for machine learning",
        "status": "completed",
    }
    assert events[-1].event_type == "completed"


@pytest.mark.asyncio
async def test_chat_loop_executes_tool_directive(tmp_path: Path) -> None:
    """Verify native tool call triggers tool_dispatcher callback."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Tool Direct Test")

    chunks = [
        StreamChunk(delta="Reading note now. ", finish_reason=None),
        StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_2",
                    name="wiki_read",
                    arguments=json.dumps({"path": "01_Notes/ml.md"}),
                )
            ],
        ),
    ]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra")

    tool_calls: list[tuple[str, dict[str, Any] | None]] = []

    async def mock_tool_dispatcher(name: str, params: dict[str, Any] | None) -> ToolExecutionResult:
        tool_calls.append((name, params))
        return ToolExecutionResult(tool_name=name, success=True, output="Note content here")

    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        tool_dispatcher=mock_tool_dispatcher,
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Read the ML note"):
        events.append(event)

    assert len(tool_calls) == 1
    assert tool_calls[0] == ("wiki_read", {"path": "01_Notes/ml.md"})

    tool_events = [e for e in events if e.event_type == "tool_executed"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_result.output == "Note content here"  # type: ignore[union-attr]
    assert events[-1].event_type == "completed"


@pytest.mark.asyncio
async def test_chat_loop_dispatch_error_resilience(tmp_path: Path) -> None:
    """Verify failed job dispatch emits error event without terminating conversation stream."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Resilience Test")

    intent = TaskIntent(
        verb=Verb.EXECUTE,
        resource="workspace.command",
        scope=Scope.WORKSPACE,
        parameters={"command": "doomed"},
        desired_output="task output",
        normalized_utterance="Doomed background task",
    )
    chunks = [
        StreamChunk(delta="Dispatching ", finish_reason=None),
        StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_3",
                    name="fulfill_request",
                    arguments=intent.model_dump_json(),
                )
            ],
        ),
    ]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra")

    async def failing_dispatcher(session_id: str, task: str) -> None:
        raise RuntimeError("Worker queue capacity exceeded")

    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        job_dispatcher=failing_dispatcher,  # type: ignore[arg-type]
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Run background task"):
        events.append(event)

    error_events = [e for e in events if e.event_type == "error"]
    assert len(error_events) == 1
    assert "Worker queue capacity exceeded" in (error_events[0].error_message or "")
    assert events[-1].event_type == "completed"


@pytest.mark.asyncio
async def test_chat_loop_dispatches_with_context_payload(tmp_path: Path) -> None:
    """Verify conversational context payload is properly passed to job_dispatcher."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Context Payload Test")

    # Seed previous turns
    repo.append_turn(session.session_id, "user", "What are the running services?", 10)
    repo.append_turn(
        session.session_id,
        "assistant",
        "Here are the active services: Redis on 6379, Postgres on 5432.",
        25,
    )

    intent = TaskIntent(
        verb=Verb.CAPTURE,
        resource="vault.note",
        scope=Scope.VAULT,
        parameters={"content": "service overview"},
        desired_output="saved note",
        normalized_utterance="Save service overview to warehouse",
    )
    chunks = [
        StreamChunk(delta="Saving those notes for you. ", finish_reason=None),
        StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_4",
                    name="fulfill_request",
                    arguments=intent.model_dump_json(),
                )
            ],
        ),
    ]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra")

    captured_kwargs: dict[str, Any] = {}

    async def mock_dispatcher(session_id: str, task: str, **kwargs: Any) -> dict[str, str]:
        captured_kwargs.update(kwargs)
        captured_kwargs["task"] = task
        return {"status": "completed"}

    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        job_dispatcher=mock_dispatcher,  # type: ignore[arg-type]
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Will you save that to our warehouse"):
        events.append(event)

    assert captured_kwargs["task"] == "Save service overview to warehouse"
    assert "context_payload" in captured_kwargs
    ctx = captured_kwargs["context_payload"]
    assert "Redis on 6379, Postgres on 5432" in ctx
    assert "Will you save that to our warehouse" in ctx


@pytest.mark.asyncio
async def test_conversational_turn_never_dispatches(tmp_path: Path) -> None:
    """Conversational turns with text and no tool calls must NEVER trigger job or tool dispatch."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Chitchat Test")

    chunks = [StreamChunk(delta="Hello there! How can I help you today?", finish_reason="stop")]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra")

    job_dispatched = False
    tool_dispatched = False

    async def mock_job(session_id: str, task: str, **kwargs: Any) -> dict[str, str]:
        nonlocal job_dispatched
        job_dispatched = True
        return {"status": "dispatched"}

    async def mock_tool(name: str, params: dict[str, Any] | None) -> ToolExecutionResult:
        nonlocal tool_dispatched
        tool_dispatched = True
        return ToolExecutionResult(tool_name=name, success=True, output="ok")

    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        job_dispatcher=mock_job,
        tool_dispatcher=mock_tool,
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Hey Astra, good morning!"):
        events.append(event)

    assert job_dispatched is False
    assert tool_dispatched is False
    assert not any(e.event_type in ("job_dispatched", "tool_executed") for e in events)
    assert events[-1].event_type == "completed"
    assert events[-1].turn is not None
    assert events[-1].turn.content == "Hello there! How can I help you today?"
