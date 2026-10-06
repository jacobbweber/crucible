from typing import Literal

from pydantic import BaseModel, Field


class TaskBrief(BaseModel):
    """Declarative task brief specifying role, invariants, and completion standards."""

    role_anchor: str = Field(min_length=1)
    core_directive: str = Field(min_length=1)
    scope_invariants: list[str] = Field(min_length=1)
    capability_strategy: str = Field(min_length=1)
    completion_standard: str = Field(min_length=1)


class RunbookDefinition(BaseModel):
    """Specification of an operational agent runbook or skill."""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1, max_length=200)
    required_tools: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)
    what_it_does: str = Field(min_length=1)
    when_to_reach_for_it: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    procedural_steps: list[str] = Field(min_length=1)
    verification_criteria: list[str] = Field(min_length=1)


class CompiledExecutionPacket(BaseModel):
    """Assembled 5-beat system prompt packet and tool manifest ready for execution."""

    system_prompt: str
    target_tools: list[str]
    token_estimate: int
    modality: Literal["direct", "react", "plan_execute_verify", "stategraph"] | None = None
