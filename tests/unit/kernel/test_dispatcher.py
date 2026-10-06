"""Unit tests for ZeroCatalogDispatcher two-stage matching and ephemeral worker assembly."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.dispatch import DispatchResult
from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.policy import ApprovalMode
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.runner import NativeRunner


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter returning predefined streaming chunks."""

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
async def test_dispatch_stage1_matched_recipe(tmp_path: Path) -> None:
    """Seed recipe for 'Morning Briefing'; dispatch task 'run morning briefing'.

    Verify stage 1 match and execution.
    """
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Briefing Session")

    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_briefing_001",
            name="Morning Briefing",
            description="Prepare daily morning briefing summary",
            execution_engine="direct",
            target_model_tier="reasoning",
            tags=["briefing", "daily"],
            required_tools=["news_fetcher"],
            timeout_seconds=300,
        ),
        markdown_path="recipes/briefing.md",
        body="Execute morning briefing routine and summarize top news.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    adapter = MockModelAdapter(
        responses=["Top morning headlines: All systems nominal across clusters."]
    )

    async def mock_news_fetcher() -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="news_fetcher", success=True, output="Cluster OK")

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={"news_fetcher": mock_news_fetcher},
    )
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
    )

    result = await dispatcher.dispatch_task(
        session_id=session.session_id,
        task="run morning briefing",
    )

    assert result.decision.stage == "matched_recipe"
    assert result.decision.matched_recipe_id == "recipe_briefing_001"
    assert result.decision.confidence_score > 0.0
    assert result.envelope.status == "completed"
    assert "All systems nominal" in result.envelope.summary
    assert result.envelope.journey_id is not None


@pytest.mark.asyncio
async def test_dispatch_stage2_ephemeral_assembly(tmp_path: Path) -> None:
    """Dispatch novel task with zero matching recipes; verify ephemeral brief synthesized."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Novel Task Session")

    brief_json = json.dumps(
        {
            "role_anchor": "Quantum Researcher",
            "core_directive": "Synthesize novel quantum teleportation routing protocol",
            "scope_invariants": [
                "Maintain context isolation",
                "Ensure verifiable telemetry",
            ],
            "capability_strategy": "Analyze network topology and execute direct synthesis",
            "completion_standard": "Protocol synthesized and verified",
            "selected_tools": ["teleport_tool"],
        }
    )
    runner_output = "Quantum routing protocol successfully synthesized."

    adapter = MockModelAdapter(responses=[brief_json, runner_output])

    async def mock_teleport() -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name="teleport_tool",
            success=True,
            output="Node 1-to-2 ready",
        )

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={"teleport_tool": mock_teleport},
    )
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
    )

    result = await dispatcher.dispatch_task(
        session_id=session.session_id,
        task="Synthesize novel quantum teleportation routing protocol",
        available_tools=["teleport_tool", "unrelated_tool"],
    )

    assert result.decision.stage == "assembled_ephemeral"
    assert result.decision.matched_recipe_id is None
    assert "teleport_tool" in result.decision.ephemeral_tools
    assert "unrelated_tool" not in result.decision.ephemeral_tools
    assert result.envelope.status == "completed"
    assert "Quantum routing protocol successfully synthesized" in result.envelope.summary


@pytest.mark.asyncio
async def test_dispatch_context_isolation(tmp_path: Path) -> None:
    """Verify parent caller receives only DispatchResult with bounded SubJobReturnEnvelope."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Parent Caller Isolation Session")

    brief_json = json.dumps(
        {
            "role_anchor": "Isolated Worker",
            "core_directive": "Execute hermetic computation",
            "scope_invariants": ["Strict zero-leakage invariant"],
            "capability_strategy": "Direct computation",
            "completion_standard": "Computation finished",
            "selected_tools": ["compute_tool"],
        }
    )
    runner_step1 = 'Thought: Running compute\n{"action": "compute_tool", "parameters": {}}'
    runner_step2 = "Hermetic computation output."

    async def mock_compute() -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="compute_tool", success=True, output="Compute OK")

    adapter = MockModelAdapter(responses=[brief_json, runner_step1, runner_step2])
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={"compute_tool": mock_compute},
    )
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
    )

    result = await dispatcher.dispatch_task(
        session_id=session.session_id,
        task="Execute isolated computation task",
        available_tools=["compute_tool"],
    )

    # 1. Returned object validation
    assert isinstance(result, DispatchResult)
    assert isinstance(result.envelope, SubJobReturnEnvelope)
    assert result.envelope.token_estimate <= 200

    # 2. Context isolation invariant: parent session turns are NOT contaminated
    turns = session_repo.get_recent_turns(session.session_id)
    assert len(turns) == 0
    assert session_repo.count_turns(session.session_id) == 0

    # 3. Scratchpad journey isolated tracking in SQLite
    scratchpad = session_repo.get_journey_scratchpad(result.envelope.journey_id)
    assert len(scratchpad) > 0
    journey = session_repo.get_journey(result.envelope.journey_id)
    assert journey is not None
    assert journey.session_id == session.session_id


@pytest.mark.asyncio
async def test_dispatch_fallback_on_missing_tools(tmp_path: Path) -> None:
    """When a recipe matches but its required tool is missing, fall back to ephemeral assembly."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Missing Tool Session")

    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_db_backup",
            name="Database Backup Routine",
            description="Perform full database backup to S3 bucket",
            execution_engine="direct",
            target_model_tier="reasoning",
            tags=["backup", "database", "s3"],
            required_tools=["s3_uploader"],
            timeout_seconds=300,
        ),
        markdown_path="recipes/backup.md",
        body="Execute full S3 backup.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    # Ephemeral planner response selecting alternative tool
    brief_json = json.dumps(
        {
            "role_anchor": "Storage Worker",
            "core_directive": "Backup database to local disk",
            "scope_invariants": ["Strict local storage"],
            "capability_strategy": "Use local_saver",
            "completion_standard": "Local backup created",
            "selected_tools": ["local_saver"],
        }
    )
    runner_output = "Database backup saved locally."
    adapter = MockModelAdapter(responses=[brief_json, runner_output])

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={},
    )
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
    )

    # Dispatch with only local_saver available (s3_uploader is missing!)
    result = await dispatcher.dispatch_task(
        session_id=session.session_id,
        task="perform database backup",
        available_tools=["local_saver"],
    )

    # Must fall through to Stage 2 instead of executing the broken recipe!
    assert result.decision.stage == "assembled_ephemeral"
    assert "local_saver" in result.decision.ephemeral_tools
    assert result.envelope.status == "completed"


@pytest.mark.asyncio
async def test_dispatch_near_miss_falls_through_to_stage2(tmp_path: Path) -> None:
    """When a task matches below threshold (near-miss), fall through to Stage 2."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Near Miss Session")

    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_kubernetes",
            name="Kubernetes Rolling Restart",
            description="Restart production cluster workloads with zero downtime",
            execution_engine="direct",
            target_model_tier="reasoning",
            tags=["k8s", "restart", "cluster"],
            required_tools=["k8s_restart"],
            timeout_seconds=300,
        ),
        markdown_path="recipes/k8s.md",
        body="Execute rolling restart.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    brief_json = json.dumps(
        {
            "role_anchor": "Cluster Worker",
            "core_directive": "Inspect cluster metrics",
            "scope_invariants": ["Read only"],
            "capability_strategy": "Check metrics",
            "completion_standard": "Metrics collected",
            "selected_tools": [],
        }
    )
    runner_output = "Cluster metrics inspected."
    adapter = MockModelAdapter(responses=[brief_json, runner_output])

    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={},
    )
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    # High threshold (e.g. 5000000.0) so near-miss fails threshold check
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
        match_threshold=5000000.0,
    )

    result = await dispatcher.dispatch_task(
        session_id=session.session_id,
        task="check restart status",
        available_tools=[],
    )

    assert result.decision.stage == "assembled_ephemeral"
    assert result.envelope.status == "completed"
