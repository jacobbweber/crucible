"""Domain models for dynamic job assembly requests, capability gaps, and pipeline results."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from agent_os.domain.dispatch import DispatchResult


class CapabilityGapReport(BaseModel):
    """Assessment of whether a task can be satisfied by existing catalog recipes or has gaps."""

    task: str
    missing_capabilities: list[str] = Field(default_factory=list)
    has_gap: bool = False
    resolution_strategy: Literal["ephemeral_synthesis", "human_intervention", "none"] = "none"
    acknowledgment: str | None = None


class JobAssemblyRequest(BaseModel):
    """Specification for assembling and executing a dynamic background job."""

    session_id: str
    task: str
    available_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=10)


class PipelineExecutionResult(BaseModel):
    """Outcome of end-to-end job assembly pipeline execution and graduation triage."""

    session_id: str
    task: str
    dispatch_result: DispatchResult
    gap_report: CapabilityGapReport
    flagged_for_graduation: bool = False
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
