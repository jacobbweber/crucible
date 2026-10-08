"""Unit tests for companion chat loop background job dispatch and direct tool execution."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.gateway import CompletionRequest, StreamChunk
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
    """Verify [DISPATCH: <task>] triggers job_dispatcher and yields job_dispatched event."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Dispatch Test")

    chunks = [
        StreamChunk(
            delta="Working on your request. [DISPATCH: Search notes for machine learning]",
            finish_reason="stop",
        )
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
    """Verify [TOOL: <name> <params>] triggers tool_dispatcher callback."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Tool Direct Test")

    chunks = [
        StreamChunk(
            delta='Reading note now. [TOOL: wiki_read {"path": "01_Notes/ml.md"}]',
            finish_reason="stop",
        )
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

    chunks = [
        StreamChunk(delta="Dispatching [DISPATCH: Doomed background task]", finish_reason="stop")
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

    chunks = [
        StreamChunk(
            delta="Saving those notes for you. [DISPATCH: Save service overview to warehouse]",
            finish_reason="stop",
        )
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

