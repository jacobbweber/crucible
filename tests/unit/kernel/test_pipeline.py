"""Unit tests for JobAssemblyPipeline end-to-end dynamic job assembly and execution."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.domain.pipeline import JobAssemblyRequest, PipelineExecutionResult
from agent_os.domain.policy import ApprovalMode
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.runner import NativeRunner
from agent_os.kernel.signaling import CompletionSignaler


class MockModelAdapter(BaseModelAdapter):
    """Hermetic model adapter returning predefined streaming response chunks."""

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
async def test_pipeline_stage1_matched_flow(tmp_path: Path) -> None:
    """Seed recipe; submit JobAssemblyRequest; verify Stage 1 match, dual signals, no graduation."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Pipeline Test Session")

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
    signaler = CompletionSignaler()
    pipeline = JobAssemblyPipeline(
        dispatcher=dispatcher,
        signaler=signaler,
        recipe_repo=recipe_repo,
    )

    req = JobAssemblyRequest(
        session_id=session.session_id,
        task="run morning briefing",
        available_tools=["news_fetcher"],
    )
    result = await pipeline.run_pipeline(req)

    assert isinstance(result, PipelineExecutionResult)
    assert result.session_id == session.session_id
    assert result.task == "run morning briefing"
    assert result.dispatch_result.decision.stage == "matched_recipe"
    assert result.dispatch_result.decision.matched_recipe_id == "recipe_briefing_001"
    assert result.dispatch_result.envelope.status == "completed"
    assert result.gap_report.has_gap is False
    assert result.gap_report.resolution_strategy == "none"
    assert result.gap_report.missing_capabilities == []
    assert result.flagged_for_graduation is False

    # Channel 1: Ambient Nudge Queue
    nudges = signaler.poll_ambient_nudges()
    assert len(nudges) == 1
    assert nudges[0].journey_id == result.dispatch_result.envelope.journey_id
    assert nudges[0].status == "completed"

    # Channel 2: Deferred Turn Prompt Injection
    prompt_block = signaler.format_deferred_prompt_block(session.session_id)
    assert prompt_block.startswith("<background_completions>")
    assert result.dispatch_result.envelope.summary in prompt_block


@pytest.mark.asyncio
async def test_pipeline_stage2_ephemeral_graduation_flagging(tmp_path: Path) -> None:
    """Submit novel task; assert Stage 2 ephemeral synthesis, dual signals, graduation flagged."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    session_repo = SessionRepository(tmp_path / "session_store.db")
    session = session_repo.create_session("Novel Ephemeral Session")

    brief_json = json.dumps(
        {
            "role_anchor": "Quantum Researcher",
            "core_directive": "Synthesize novel quantum protocol",
            "scope_invariants": ["Strict context isolation"],
            "capability_strategy": "Execute direct synthesis",
            "completion_standard": "Protocol synthesized",
            "selected_tools": ["teleport_tool"],
        }
    )
    runner_output = "Quantum protocol successfully synthesized."
    adapter = MockModelAdapter(responses=[brief_json, runner_output])

    async def mock_teleport() -> ToolExecutionResult:
        return ToolExecutionResult(tool_name="teleport_tool", success=True, output="Teleport OK")

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
    signaler = CompletionSignaler()
    pipeline = JobAssemblyPipeline(
        dispatcher=dispatcher,
        signaler=signaler,
        recipe_repo=recipe_repo,
    )

    req = JobAssemblyRequest(
        session_id=session.session_id,
        task="Synthesize novel quantum teleportation routing protocol",
        available_tools=["teleport_tool"],
    )
    result = await pipeline.run_pipeline(req)

    assert result.dispatch_result.decision.stage == "assembled_ephemeral"
    assert result.dispatch_result.envelope.status == "completed"
    assert result.flagged_for_graduation is True
    assert result.gap_report.has_gap is True
    assert result.gap_report.resolution_strategy == "ephemeral_synthesis"

    # Dual Channel Verifications
    nudges = signaler.poll_ambient_nudges()
    assert len(nudges) == 1
    assert nudges[0].status == "completed"

    prompt_block = signaler.format_deferred_prompt_block(session.session_id)
    assert "<background_completions>" in prompt_block
    assert result.dispatch_result.envelope.journey_id in prompt_block


def test_pipeline_capability_gap_triage(tmp_path: Path) -> None:
    """Test triage logic when required tools are present vs missing vs no recipe match."""
    recipe_repo = RecipeRepository(tmp_path / "recipes.db")
    recipe_record = RecipeRecord(
        metadata=RecipeMetadata(
            recipe_id="recipe_multi_001",
            name="Multimedia Pipeline",
            description="Process video and audio streams into transcripts",
            execution_engine="react",
            target_model_tier="reasoning",
            tags=["video", "audio"],
            required_tools=["video_decoder", "audio_transcriber"],
            timeout_seconds=300,
        ),
        markdown_path="recipes/multimedia.md",
        body="Extract audio and decode video streams.",
    )
    recipe_repo.upsert_recipe(recipe_record)

    adapter = MockModelAdapter(responses=[])
    runner = NativeRunner(
        model_adapter=adapter,
        policy_gate=ToolPolicyGate(ApprovalMode.BALANCED),
        tool_dispatcher={},
    )
    session_repo = SessionRepository(tmp_path / "session_store.db")
    chamber = RecipeChamber(runner=runner, session_repo=session_repo)
    dispatcher = ZeroCatalogDispatcher(
        recipe_repo=recipe_repo,
        recipe_chamber=chamber,
        model_adapter=adapter,
    )
    signaler = CompletionSignaler()
    pipeline = JobAssemblyPipeline(
        dispatcher=dispatcher,
        signaler=signaler,
        recipe_repo=recipe_repo,
    )

    # Case A: Stored recipe matches and all required tools are present
    report_a = pipeline.triage_capability_gap(
        task="process video and audio streams",
        available_tools=["video_decoder", "audio_transcriber", "extra_tool"],
    )
    assert report_a.has_gap is False
    assert report_a.missing_capabilities == []
    assert report_a.resolution_strategy == "none"

    # Case B: Stored recipe matches but required tool is missing
    report_b = pipeline.triage_capability_gap(
        task="process video and audio streams",
        available_tools=["video_decoder"],
    )
    assert report_b.has_gap is True
    assert report_b.missing_capabilities == ["audio_transcriber"]
    assert report_b.resolution_strategy == "ephemeral_synthesis"

    # Case C: No recipe match at all
    report_c = pipeline.triage_capability_gap(
        task="unrelated novel space exploration task",
        available_tools=["video_decoder"],
    )
    assert report_c.has_gap is True
    assert report_c.missing_capabilities == []
    assert report_c.resolution_strategy == "ephemeral_synthesis"
