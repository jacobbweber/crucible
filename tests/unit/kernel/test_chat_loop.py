"""Unit tests for CompanionChatLoop conversation flow, sliding window, and persistence."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.companion import CompanionConfig, TonePreset
from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.chat_loop import CompanionChatLoop


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter capturing requests and yielding pre-configured stream chunks."""

    def __init__(self, chunks: list[StreamChunk]) -> None:
        self.chunks = chunks
        self.requests: list[CompletionRequest] = []

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        for chunk in self.chunks:
            yield chunk


class FailingModelAdapter(BaseModelAdapter):
    """Model adapter simulating an unhandled model inference or provider failure."""

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        raise RuntimeError("Model inference failed: GPU OOM")
        # Yield to ensure the method is typed as an async generator
        yield StreamChunk(delta="")


@pytest.mark.asyncio
async def test_chat_loop_turn_streaming_and_persistence(tmp_path: Path) -> None:
    """Submit user turn, verify streamed deltas, and verify turn persistence."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Streaming Test")

    chunks = [
        StreamChunk(delta="Hello", finish_reason=None),
        StreamChunk(delta=" world!", finish_reason="stop"),
    ]
    adapter = MockModelAdapter(chunks)
    config = CompanionConfig(name="Astra", tone=TonePreset.CONCISE)
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        sliding_window_size=15,
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Hi Astra"):
        events.append(event)

    # Verify stream deltas and completion
    deltas = [e.delta for e in events if e.event_type == "delta"]
    assert deltas == ["Hello", " world!"]
    assert events[-1].event_type == "completed"
    assert events[-1].turn is not None
    assert events[-1].turn.role == "assistant"
    assert events[-1].turn.content == "Hello world!"

    # Verify SQLite persistence
    stored_turns = repo.get_recent_turns(session.session_id, limit=10)
    assert len(stored_turns) == 2
    assert stored_turns[0].role == "user"
    assert stored_turns[0].content == "Hi Astra"
    assert stored_turns[1].role == "assistant"
    assert stored_turns[1].content == "Hello world!"

    # Verify session state query
    state = loop.get_state()
    assert state.session_id == session.session_id
    assert len(state.active_turns) == 2
    assert state.total_turns_recorded == 2


@pytest.mark.asyncio
async def test_chat_loop_sliding_window_bound(tmp_path: Path) -> None:
    """Verify sliding window bounds request to system prompt + 15 recent turns + active turn."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("History Window Test")

    # Seed 25 historical turns
    for i in range(25):
        repo.append_turn(
            session_id=session.session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"History message {i}",
        )

    adapter = MockModelAdapter([StreamChunk(delta="Understood", finish_reason="stop")])
    config = CompanionConfig(name="Astra")
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        sliding_window_size=15,
    )

    async for _ in loop.execute_turn("Brand new user input"):
        pass

    assert len(adapter.requests) == 1
    messages = adapter.requests[0].messages

    # Exactly 1 System Prompt + 15 historical turns + 1 Active user turn = 17 messages
    assert len(messages) == 1 + 15 + 1
    assert messages[0].role == "system"
    assert messages[1].content == "History message 10"
    assert messages[15].content == "History message 24"
    assert messages[16].role == "user"
    assert messages[16].content == "Brand new user input"


@pytest.mark.asyncio
async def test_chat_loop_recalled_facts_injection(tmp_path: Path) -> None:
    """Verify recalled facts XML tags are injected into system message delivered to adapter."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Facts Injection Test")

    adapter = MockModelAdapter([StreamChunk(delta="Noted", finish_reason="stop")])
    config = CompanionConfig(name="Astra")
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
    )

    facts = "User prefers concise Python code and uses uv package manager."
    async for _ in loop.execute_turn("What tooling do I use?", recalled_facts_block=facts):
        pass

    assert len(adapter.requests) == 1
    system_msg = adapter.requests[0].messages[0]
    assert system_msg.role == "system"
    assert "<recalled_facts>" in system_msg.content
    assert facts in system_msg.content
    assert "</recalled_facts>" in system_msg.content


@pytest.mark.asyncio
async def test_chat_loop_error_handling(tmp_path: Path) -> None:
    """Verify adapter exceptions yield error event cleanly without an unhandled crash."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Error Handling Test")

    adapter = FailingModelAdapter()
    config = CompanionConfig(name="Astra")
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Crash test"):
        events.append(event)

    assert len(events) == 1
    assert events[0].event_type == "error"
    assert events[0].error_message is not None
    assert "Model inference failed: GPU OOM" in events[0].error_message


@pytest.mark.asyncio
async def test_chat_loop_auto_creates_session_if_missing(tmp_path: Path) -> None:
    """Verify executing a turn with an uncreated session ID auto-provisions session (M2)."""
    repo = SessionRepository(tmp_path / "sessions.db")
    unregistered_session_id = "unknown_sess_999"

    adapter = MockModelAdapter([StreamChunk(delta="OK", finish_reason="stop")])
    config = CompanionConfig(name="Astra")
    loop = CompanionChatLoop(
        session_id=unregistered_session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
    )

    events: list[StreamTurnEvent] = []
    async for event in loop.execute_turn("Auto provision me"):
        events.append(event)

    assert events[-1].event_type == "completed"
    assert repo.get_session(unregistered_session_id) is not None
    stored_turns = repo.get_recent_turns(unregistered_session_id)
    assert len(stored_turns) == 2


@pytest.mark.asyncio
async def test_chat_loop_token_budget_pruning(tmp_path: Path) -> None:
    """Verify history turns are pruned to stay within context window token budget (M5)."""
    repo = SessionRepository(tmp_path / "sessions.db")
    session = repo.create_session("Budget Pruning Test")

    # Seed 5 large turns of ~200 tokens each
    large_text = "word " * 180  # ~180 tokens
    for i in range(5):
        repo.append_turn(
            session_id=session.session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"Turn {i}: {large_text}",
        )

    adapter = MockModelAdapter([StreamChunk(delta="Done", finish_reason="stop")])
    config = CompanionConfig(name="Astra")
    # Setting tight context window: 800 tokens, 200 output reserve -> history budget ~400 tokens
    loop = CompanionChatLoop(
        session_id=session.session_id,
        session_repo=repo,
        model_adapter=adapter,
        config=config,
        sliding_window_size=15,
        context_window=800,
        reserve_output_tokens=200,
    )

    async for _ in loop.execute_turn("Next query"):
        pass

    assert len(adapter.requests) == 1
    messages = adapter.requests[0].messages
    # System prompt + pruned history + active user turn
    # With 180-token turns and history budget ~400, at most 2 historical turns can fit!
    history_messages = [m for m in messages if m.role in ("user", "assistant")][:-1]
    assert len(history_messages) < 5
    assert len(history_messages) >= 1
    # Check that the most recent history turn (Turn 4) was preserved
    assert "Turn 4" in history_messages[-1].content
