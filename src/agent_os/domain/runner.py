"""Domain models for execution requests, runner step events, and results."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from agent_os.domain.tools import ToolDefinition

ExecutionModality = Literal["direct", "react", "plan_execute_verify", "stategraph"]


class RunnerStepEvent(BaseModel):
    """Event emitted for an individual execution step."""

    step_index: int
    modality: ExecutionModality
    step_type: Literal["thought", "tool_call", "tool_result", "plan", "verify", "node_transition"]
    content: str
    tool_name: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output: str | None = None
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RunnerExecutionRequest(BaseModel):
    """Specification for invoking a native runner execution."""

    task: str
    modality: ExecutionModality = "react"
    system_prompt: str = ""
    max_turns: int = Field(default=15, ge=1, le=50)
    timeout_seconds: int = Field(default=300, ge=10)
    tools: list[ToolDefinition] = Field(default_factory=list)


class RunnerResult(BaseModel):
    """Final outcome and step sequence produced by an execution run."""

    success: bool
    final_output: str
    steps: list[RunnerStepEvent] = Field(default_factory=list)
    total_turns: int = 0
    error: str | None = None
    aborted_by_cycle_detection: bool = False
