"""Domain models for IPC requests, return envelopes, and sub-job execution."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_os.domain.runbook import CompiledExecutionPacket


class SubJobReturnEnvelope(BaseModel):
    """Bounded, compressed return envelope from an isolated worker journey."""

    journey_id: str
    status: Literal["completed", "failed", "aborted"]
    summary: str = Field(max_length=800)
    artifact_paths: list[str] = Field(default_factory=list)
    state_mutations: list[str] = Field(default_factory=list)
    token_estimate: int
    duration_ms: int = 0
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubJobExecutionRequest(BaseModel):
    """Specification for invoking an isolated sub-job worker execution."""

    session_id: str
    task: str
    packet: CompiledExecutionPacket
    timeout_seconds: int = Field(default=300, ge=10)
    context_payload: str = ""
