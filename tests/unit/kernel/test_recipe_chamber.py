"""Unit tests for RecipeChamber sub-job execution, scratchpad persistence, and context isolation."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.ipc import SubJobExecutionRequest
from agent_os.domain.policy import ActionTier, ApprovalMode, PolicyDecisionType
from agent_os.domain.runbook import CompiledExecutionPacket
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.runner import NativeRunner


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter returning sequential predefined responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.call_count = 0

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        if self.responses:
            idx = min(self.call_count, len(self.responses) - 1)
            resp = self.responses[idx]
            self.call_count += 1
            yield StreamChunk(delta=resp)
        else:
            yield StreamChunk(delta="")


@pytest.mark.asyncio
async def test_recipe_chamber_persists_journey_and_steps(tmp_path: Path) -> None:
    """Execute sub-job; verify journey and journey_steps exist in session_store.db."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Parent Task Session")

    adapter = MockModelAdapter(
        responses=[
            (
                "Thought: Querying cache state\n"
                '{"action": "check_redis", "parameters": {"cluster": "main"}}'
            ),
            "Redis cluster 'main' is healthy and operational.",
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_redis(cluster: str) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name="check_redis",
            success=True,
            output=f"Cluster {cluster}: OK",
        )

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"check_redis": mock_redis},
    )
    chamber = RecipeChamber(runner=runner, session_repo=repo)

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=["check_redis"],
        token_estimate=5,
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Verify Redis health",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)

    assert envelope.status == "completed"
    assert "Redis cluster 'main' is healthy" in envelope.summary

    # Verify journey persistence in SQLite
    journey = repo.get_journey(envelope.journey_id)
    assert journey is not None
    assert journey.journey_id == envelope.journey_id
    assert journey.session_id == session.session_id
    assert journey.status == "completed"
    assert journey.task == "Verify Redis health"

    # Verify journey_steps persistence in scratchpad
    steps = repo.get_journey_scratchpad(envelope.journey_id)
    assert len(steps) == 3
    assert steps[0]["node_name"] == "thought"
    assert steps[1]["node_name"] == "tool_call"
    assert steps[2]["node_name"] == "tool_result"


@pytest.mark.asyncio
async def test_recipe_chamber_context_isolation(tmp_path: Path) -> None:
    """Verify parent session turns in session_store.db contain zero intermediate worker steps."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Parent Isolation Session")

    adapter = MockModelAdapter(
        responses=[
            'Thought: Inspecting logs\n{"action": "view_logs", "parameters": {}}',
            "All logs clear.",
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_logs() -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="view_logs", success=True, output="Log content")

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"view_logs": mock_logs},
    )
    chamber = RecipeChamber(runner=runner, session_repo=repo)

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=["view_logs"],
        token_estimate=5,
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Inspect worker logs",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)
    assert envelope.status == "completed"

    # Context isolation check: parent session turns must NOT contain any worker steps
    turns = repo.get_recent_turns(session.session_id)
    assert len(turns) == 0
    assert repo.count_turns(session.session_id) == 0


@pytest.mark.asyncio
async def test_recipe_chamber_failure_marshaling(tmp_path: Path) -> None:
    """Mock runner failure/abortion; verify journey status is failed and envelope has error."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Failure Test Session")

    adapter = MockModelAdapter(
        responses=['{"action": "dangerous_action", "parameters": {"flag": true}}']
    )
    gate = ToolPolicyGate(
        ApprovalMode.BALANCED,
        explicit_overrides={"dangerous_action": PolicyDecisionType.BLOCK},
    )

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={},
    )
    chamber = RecipeChamber(runner=runner, session_repo=repo)

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=["dangerous_action"],
        token_estimate=5,
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Perform dangerous action",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)

    assert envelope.status == "failed"
    assert "Policy gate blocked tool dangerous_action" in envelope.summary
    assert envelope.token_estimate <= 200

    # Verify journey status updated in SQLite
    journey = repo.get_journey(envelope.journey_id)
    assert journey is not None
    assert journey.status == "failed"
    assert "Policy gate blocked" in (journey.summary or "")


@pytest.mark.asyncio
async def test_recipe_chamber_preserves_destructive_tier_blocks_in_balanced(
    tmp_path: Path,
) -> None:
    """Verify DESTRUCTIVE tools are not bypassed as STATE_CHANGE in BALANCED mode."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Destructive Task Session")

    adapter = MockModelAdapter(
        responses=[
            '{"action": "drop_all_tables", "parameters": {"confirm": true}}',
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.BALANCED)

    async def mock_drop(**kw: object) -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="drop_all_tables", success=True, output="dropped")

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"drop_all_tables": mock_drop},
    )
    # Pass tool_tiers with drop_all_tables as DESTRUCTIVE (NO explicit override)
    chamber = RecipeChamber(
        runner=runner,
        session_repo=repo,
        tool_tiers={"drop_all_tables": ActionTier.DESTRUCTIVE},
    )

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=["drop_all_tables"],
        token_estimate=5,
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Drop database tables",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)

    assert envelope.status == "failed"
    assert "Policy gate blocked tool drop_all_tables" in envelope.summary
    assert "Destructive operations require confirmation in balanced mode" in envelope.summary


@pytest.mark.asyncio
async def test_recipe_chamber_preserves_read_tier_allows_in_strict(
    tmp_path: Path,
) -> None:
    """Verify READ tools are not misclassified as STATE_CHANGE and succeed in STRICT mode."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Read Task Session")

    adapter = MockModelAdapter(
        responses=[
            '{"action": "safe_read", "parameters": {"path": "notes.md"}}',
            "Note content read successfully.",
        ]
    )
    gate = ToolPolicyGate(ApprovalMode.STRICT)

    async def mock_read(path: str) -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="safe_read", success=True, output="note body")

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=gate,
        tool_dispatcher={"safe_read": mock_read},
    )
    chamber = RecipeChamber(
        runner=runner,
        session_repo=repo,
        tool_tiers={"safe_read": ActionTier.READ},
    )

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=["safe_read"],
        token_estimate=5,
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Read notes safely",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)

    assert envelope.status == "completed"
    assert "read successfully" in envelope.summary


@pytest.mark.asyncio
async def test_recipe_chamber_routes_packet_modality(tmp_path: Path) -> None:
    """Verify RecipeChamber honors packet.modality instead of defaulting to react (H2)."""
    db_file = tmp_path / "session_store.db"
    repo = SessionRepository(db_file)
    session = repo.create_session("Modality Routing Session")

    adapter = MockModelAdapter(
        responses=[
            "Step 1: Inspect. Step 2: Conclude.",
            "Inspection executed.",
            "Verification confirmed.",
        ]
    )
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={},
    )
    chamber = RecipeChamber(runner=runner, session_repo=repo)

    packet = CompiledExecutionPacket(
        system_prompt="System instructions",
        target_tools=[],
        token_estimate=5,
        modality="plan_execute_verify",
    )
    request = SubJobExecutionRequest(
        session_id=session.session_id,
        task="Test plan execute verify routing",
        packet=packet,
    )

    envelope = await chamber.execute_sub_job(request)

    assert envelope.status == "completed"
    assert "Verification confirmed" in envelope.summary

    # Verify journey_steps in scratchpad show PEV nodes, not react
    steps = repo.get_journey_scratchpad(envelope.journey_id)
    assert len(steps) == 3
    assert [s["node_name"] for s in steps] == ["plan", "thought", "verify"]

