"""Deterministic command guardrail and tool execution policy gate."""

from agent_os.domain.policy import (
    ActionTier,
    ApprovalMode,
    PolicyDecision,
    PolicyDecisionType,
    ToolCallRequest,
)


class ToolPolicyGate:
    """Evaluates tool execution requests against active approval modes and explicit overrides."""

    def __init__(
        self,
        approval_mode: ApprovalMode = ApprovalMode.BALANCED,
        explicit_overrides: dict[str, PolicyDecisionType] | None = None,
    ) -> None:
        self.approval_mode = approval_mode
        self.overrides: dict[str, PolicyDecisionType] = (
            explicit_overrides.copy() if explicit_overrides else {}
        )

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        """Update active approval mode."""
        self.approval_mode = mode

    def add_override(self, tool_name: str, decision: PolicyDecisionType) -> None:
        """Set explicit override for a specific tool."""
        self.overrides[tool_name] = decision

    def evaluate(self, request: ToolCallRequest) -> PolicyDecision:
        """Evaluate a tool execution request against overrides and active approval policy."""
        # Step 1: Explicit Override Check
        if request.tool_name in self.overrides:
            override_decision = self.overrides[request.tool_name]
            return PolicyDecision(
                decision=override_decision,
                tool_name=request.tool_name,
                action_tier=request.action_tier,
                reason="Explicit tool override",
                requires_prompt=(override_decision == PolicyDecisionType.REQUIRE_CONFIRMATION),
            )

        # Step 2: Mode-Based Evaluation
        if self.approval_mode == ApprovalMode.AUTONOMOUS:
            return PolicyDecision(
                decision=PolicyDecisionType.ALLOW,
                tool_name=request.tool_name,
                action_tier=request.action_tier,
                reason="Autonomous mode allows all operations",
                requires_prompt=False,
            )

        if self.approval_mode == ApprovalMode.BALANCED:
            if request.action_tier in (ActionTier.READ, ActionTier.STATE_CHANGE):
                return PolicyDecision(
                    decision=PolicyDecisionType.ALLOW,
                    tool_name=request.tool_name,
                    action_tier=request.action_tier,
                    reason=f"{request.action_tier.value} operations allowed in balanced mode",
                    requires_prompt=False,
                )
            return PolicyDecision(
                decision=PolicyDecisionType.REQUIRE_CONFIRMATION,
                tool_name=request.tool_name,
                action_tier=request.action_tier,
                reason="Destructive operations require confirmation in balanced mode",
                requires_prompt=True,
            )

        # ApprovalMode.STRICT
        if request.action_tier == ActionTier.READ:
            return PolicyDecision(
                decision=PolicyDecisionType.ALLOW,
                tool_name=request.tool_name,
                action_tier=request.action_tier,
                reason="Read operations allowed in strict mode",
                requires_prompt=False,
            )

        return PolicyDecision(
            decision=PolicyDecisionType.REQUIRE_CONFIRMATION,
            tool_name=request.tool_name,
            action_tier=request.action_tier,
            reason=f"{request.action_tier.value} operations require confirmation in strict mode",
            requires_prompt=True,
        )
