"""Unit tests for NativeRunner execution modalities, cycle detection, and policy gates."""

from collections.abc import AsyncIterator

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.policy import ActionTier, ApprovalMode, PolicyDecisionType
from agent_os.domain.runner import RunnerExecutionRequest
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.runner import NativeRunner


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter returning sequential predefined responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.call_count = 0
        self.requests: list[CompletionRequest] = []

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        if self.responses:
            idx = min(self.call_count, len(self.responses) - 1)
            resp = self.responses[idx]
            self.call_count += 1
            yield StreamChunk(delta=resp)
        else:
            yield StreamChunk(delta="")


@pytest.mark.asyncio
async def test_runner_direct_modality() -> None:
    """Execute with modality='direct'; verify single completion without tool invocations."""
    adapter = MockModelAdapter(responses=["Direct answer without tool execution."])
    gate = ToolPolicyGate(ApprovalMode.BALANCED)
    runner = NativeRunner(model_adapter=adapter, policy_gate=gate, tool_dispatcher={})

    request = RunnerExecutionRequest(
        task="Summarize this brief",
        modality="direct",
    )
    result = await runner.execute(request)

    assert result.success is True
    assert result.final_output == "Direct answer without tool execution."
    assert result.total_turns == 1
    assert len(result.steps) == 1
    assert result.steps[0].step_type == "thought"
    assert not any(s.step_type == "tool_call" for s in result.steps)


@pytest.mark.asyncio
async def test_runner_react_success() -> None:
    """Propose tool call followed by final answer; verify thought -> tool_call -> tool_result."""
    adapter = MockModelAdapter(
        responses=[
            (
                "Thought: Checking customer balance\n"
                '{"action": "get_balance", "parameters": {"account_id": "acc_42"}}'
            ),
            "The customer account acc_42 has a verified balance of $1,500.",
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_get_balance(account_id: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name="get_balance",
            success=True,
            output=f"Account {account_id} balance: $1,500",
        )

    tool_def = ToolDefinition(
        name="get_balance",
        description="Fetch account balance",
        action_tier=ActionTier.READ,
    )
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"get_balance": mock_get_balance},
    )

    request = RunnerExecutionRequest(
        task="Check balance for acc_42",
        modality="react",
        tools=[tool_def],
    )
    result = await runner.execute(request)

    assert result.success is True
    assert result.final_output == "The customer account acc_42 has a verified balance of $1,500."
    assert result.total_turns == 2
    assert len(result.steps) == 3

    assert result.steps[0].step_type == "thought"
    assert "Checking customer balance" in result.steps[0].content

    assert result.steps[1].step_type == "tool_call"
    assert result.steps[1].tool_name == "get_balance"
    assert result.steps[1].tool_input == {"account_id": "acc_42"}

    assert result.steps[2].step_type == "tool_result"
    assert result.steps[2].tool_name == "get_balance"
    assert "$1,500" in (result.steps[2].tool_output or "")


@pytest.mark.asyncio
async def test_runner_react_cycle_detection() -> None:
    """Repeatedly return identical tool call 3 times; verify runner aborts with cycle detection."""
    adapter = MockModelAdapter(
        responses=[
            'Thought: Pinging node\n{"action": "ping_node", "parameters": {"node_id": "node_1"}}'
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_ping(node_id: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name="ping_node",
            success=True,
            output=f"Node {node_id} alive",
        )

    tool_def = ToolDefinition(
        name="ping_node",
        description="Ping cluster node",
        action_tier=ActionTier.READ,
    )
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"ping_node": mock_ping},
    )

    request = RunnerExecutionRequest(
        task="Check node status",
        modality="react",
        max_turns=10,
        tools=[tool_def],
    )
    result = await runner.execute(request)

    assert result.success is False
    assert result.aborted_by_cycle_detection is True
    assert result.error == "Cycle detected: tool called 3x with identical arguments"
    assert result.total_turns == 3


@pytest.mark.asyncio
async def test_runner_react_turn_budget_exhaustion() -> None:
    """Set max_turns=3; mock infinite unique tool calls; verify termination upon budget limit."""
    adapter = MockModelAdapter(
        responses=[
            '{"action": "step_tool", "parameters": {"step": 1}}',
            '{"action": "step_tool", "parameters": {"step": 2}}',
            '{"action": "step_tool", "parameters": {"step": 3}}',
            '{"action": "step_tool", "parameters": {"step": 4}}',
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_step(step: int) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name="step_tool",
            success=True,
            output=f"Executed step {step}",
        )

    tool_def = ToolDefinition(
        name="step_tool",
        description="Step tool",
        action_tier=ActionTier.READ,
    )
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"step_tool": mock_step},
    )

    request = RunnerExecutionRequest(
        task="Execute long workflow",
        modality="react",
        max_turns=3,
        tools=[tool_def],
    )
    result = await runner.execute(request)

    assert result.success is False
    assert result.aborted_by_cycle_detection is False
    assert result.total_turns == 3
    assert result.error is not None
    assert "Turn limit" in result.error


@pytest.mark.asyncio
async def test_runner_policy_gate_blocks_execution() -> None:
    """Tool evaluated by policy gate returns BLOCK; verify step records failure and halts."""
    adapter = MockModelAdapter(
        responses=[
            'Thought: Purging database\n{"action": "drop_tables", "parameters": {"confirm": true}}'
        ]
    )
    gate = ToolPolicyGate(
        ApprovalMode.BALANCED,
        explicit_overrides={"drop_tables": PolicyDecisionType.BLOCK},
    )

    async def mock_drop(confirm: bool) -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="drop_tables", success=True, output="Dropped")

    tool_def = ToolDefinition(
        name="drop_tables",
        description="Drop all database tables",
        action_tier=ActionTier.DESTRUCTIVE,
    )
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"drop_tables": mock_drop},
    )

    request = RunnerExecutionRequest(
        task="Clean up system",
        modality="react",
        tools=[tool_def],
    )
    result = await runner.execute(request)

    assert result.success is False
    assert result.error is not None
    assert "Policy gate blocked tool drop_tables" in result.error

    # Verify failure recorded in step event
    assert any(
        s.step_type == "tool_result" and "Policy gate blocked" in s.content for s in result.steps
    )
