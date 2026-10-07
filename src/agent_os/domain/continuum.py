"""Domain models for companion chat continuum, session state, and streaming turn events."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_os.domain.session import TurnRecord


class StreamTurnEvent(BaseModel):
    """Event emitted during interactive streaming turn execution."""

    event_type: Literal[
        "delta", "completed", "error", "thinking", "job_dispatched", "tool_executed", "status"
    ]
    delta: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    turn: TurnRecord | None = None
    error_message: str | None = None
    dispatched_job: Any | None = None
    tool_result: Any | None = None


class ChatSessionState(BaseModel):
    """Snapshot of active chat session state within a bounded sliding window."""

    session_id: str
    active_turns: list[TurnRecord] = Field(default_factory=list)
    sliding_window_size: int = 15
    total_turns_recorded: int = 0
