"""Unit tests for ToolPolicyGate guardrails, modes, and explicit tool overrides."""

from agent_os.domain.policy import (
    ActionTier,
    ApprovalMode,
    PolicyDecisionType,
    ToolCallRequest,
)
from agent_os.kernel.policy_gate import ToolPolicyGate


def test_balanced_mode_read_allowed() -> None:
    """Verify ActionTier.READ in BALANCED mode returns ALLOW without prompt."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.BALANCED)
    request = ToolCallRequest(tool_name="view_file", action_tier=ActionTier.READ)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.ALLOW
    assert not decision.requires_prompt
    assert decision.tool_name == "view_file"
    assert decision.action_tier == ActionTier.READ


def test_balanced_mode_state_change_allowed() -> None:
    """Verify ActionTier.STATE_CHANGE in BALANCED mode returns ALLOW without prompt."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.BALANCED)
    request = ToolCallRequest(tool_name="update_config", action_tier=ActionTier.STATE_CHANGE)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.ALLOW
    assert not decision.requires_prompt
    assert decision.tool_name == "update_config"
    assert decision.action_tier == ActionTier.STATE_CHANGE


def test_balanced_mode_destructive_requires_confirmation() -> None:
    """Verify ActionTier.DESTRUCTIVE in BALANCED mode returns REQUIRE_CONFIRMATION with prompt."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.BALANCED)
    request = ToolCallRequest(tool_name="drop_table", action_tier=ActionTier.DESTRUCTIVE)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.REQUIRE_CONFIRMATION
    assert decision.requires_prompt
    assert decision.tool_name == "drop_table"
    assert decision.action_tier == ActionTier.DESTRUCTIVE
    assert "Destructive operations require confirmation in balanced mode" in decision.reason


def test_strict_mode_state_change_requires_confirmation() -> None:
    """Verify ActionTier.STATE_CHANGE in STRICT mode returns REQUIRE_CONFIRMATION with prompt."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.STRICT)
    request = ToolCallRequest(tool_name="write_file", action_tier=ActionTier.STATE_CHANGE)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.REQUIRE_CONFIRMATION
    assert decision.requires_prompt
    assert decision.tool_name == "write_file"
    assert decision.action_tier == ActionTier.STATE_CHANGE
    assert "state_change operations require confirmation in strict mode" in decision.reason


def test_autonomous_mode_allows_destructive() -> None:
    """Verify ActionTier.DESTRUCTIVE in AUTONOMOUS mode returns ALLOW without prompt."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.AUTONOMOUS)
    request = ToolCallRequest(tool_name="delete_database", action_tier=ActionTier.DESTRUCTIVE)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.ALLOW
    assert not decision.requires_prompt
    assert decision.tool_name == "delete_database"
    assert decision.action_tier == ActionTier.DESTRUCTIVE


def test_explicit_override_precedence() -> None:
    """Verify explicit override blocks execution even when active mode is AUTONOMOUS."""
    gate = ToolPolicyGate(
        approval_mode=ApprovalMode.AUTONOMOUS,
        explicit_overrides={"delete_file": PolicyDecisionType.BLOCK},
    )
    request = ToolCallRequest(tool_name="delete_file", action_tier=ActionTier.DESTRUCTIVE)
    decision = gate.evaluate(request)

    assert decision.decision == PolicyDecisionType.BLOCK
    assert not decision.requires_prompt
    assert decision.tool_name == "delete_file"
    assert decision.reason == "Explicit tool override"


def test_undeclared_action_defaults_to_destructive() -> None:
    """Verify omitted action_tier defaults to DESTRUCTIVE and triggers confirmation in BALANCED."""
    gate = ToolPolicyGate(approval_mode=ApprovalMode.BALANCED)
    request = ToolCallRequest(tool_name="unknown_action")

    assert request.action_tier == ActionTier.DESTRUCTIVE
    decision = gate.evaluate(request)

    assert decision.action_tier == ActionTier.DESTRUCTIVE
    assert decision.decision == PolicyDecisionType.REQUIRE_CONFIRMATION
    assert decision.requires_prompt
