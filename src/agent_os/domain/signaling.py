"""Domain models for background task completion signaling and prompt injection."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_os.domain.ipc import SubJobReturnEnvelope


class AmbientNudge(BaseModel):
    """Compact notification representing an ambient event for UI toast or canvas banner."""

    nudge_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    journey_id: str = Field(min_length=1)
    status: Literal["completed", "failed", "aborted"]
    short_notice: str = Field(max_length=120)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeferredCompletionBuffer(BaseModel):
    """Buffer holding completed background sub-job return envelopes for a session."""

    session_id: str
    pending_envelopes: list[SubJobReturnEnvelope] = Field(default_factory=list)
