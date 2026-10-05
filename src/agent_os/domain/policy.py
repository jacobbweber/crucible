"""Domain models for execution policy, approval tiers, and tool call requests."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ApprovalMode(StrEnum):
    """Operational approval profiles for tool execution."""

    AUTONOMOUS = "autonomous"
    BALANCED = "balanced"
    STRICT = "strict"


class ActionTier(StrEnum):
    """Classification tiers reflecting tool execution impact and risk."""

    READ = "read"
    STATE_CHANGE = "state_change"
    DESTRUCTIVE = "destructive"


class PolicyDecisionType(StrEnum):
    """Evaluated policy verdicts."""

    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCK = "block"


class ToolCallRequest(BaseModel):
    """Represents an incoming tool execution request to be evaluated against policy."""

    tool_name: str
    action_tier: ActionTier = ActionTier.DESTRUCTIVE
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    origin_session_id: str | None = None
    origin_journey_id: str | None = None


class PolicyDecision(BaseModel):
    """Result of policy evaluation indicating whether an action is permitted."""

    decision: PolicyDecisionType
    tool_name: str
    action_tier: ActionTier
    reason: str
    requires_prompt: bool = False
