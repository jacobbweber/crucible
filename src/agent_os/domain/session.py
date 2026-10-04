"""Domain models for sessions, conversation turns, and background journey scratchpads."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TurnRecord(BaseModel):
    """Represents a single conversation turn in a session."""

    turn_id: str
    session_id: str
    turn_index: int
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    token_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JourneyRecord(BaseModel):
    """Represents an isolated background task/journey execution record."""

    journey_id: str
    session_id: str
    task: str
    status: Literal["running", "completed", "failed", "aborted"]
    summary: str | None = None
    artifacts: list[str] = Field(default_factory=list)
    state_mutations: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class SessionRecord(BaseModel):
    """Represents an interactive conversation session."""

    session_id: str
    title: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_archived: bool = False
