"""Unit tests for dynamic planning UX acknowledgment ('Building Capability')."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.dispatch import DispatchDecision, DispatchResult
from agent_os.domain.gateway import CompletionRequest, StreamChunk, ToolCallPart
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.vocabulary import Scope, Verb
from agent_os.domain.ipc import SubJobReturnEnvelope
from agent_os.domain.pipeline import JobAssemblyRequest
from agent_os.domain.session import SessionRecord, TurnRecord
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.signaling import CompletionSignaler


@pytest.fixture
def mock_recipe_repo() -> MagicMock:
    repo = MagicMock(spec=RecipeRepository)
    repo.match_intent.return_value = []
    return repo


@pytest.fixture
def mock_dispatcher() -> MagicMock:
    dispatcher = MagicMock(spec=ZeroCatalogDispatcher)
    dispatcher.threshold = 0.5
    envelope = SubJobReturnEnvelope(
        journey_id="jrn_test_123",
        status="completed",
        summary="Dynamic task completed",
        artifact_paths=[],
        state_mutations=[],
        duration_ms=100,
        token_estimate=50,
    )
    decision = DispatchDecision(
        task="deploy microservice",
        stage="assembled_ephemeral",
        ephemeral_tools=["shell_exec"],
    )
    dispatcher.dispatch_task = AsyncMock(
        return_value=DispatchResult(decision=decision, envelope=envelope)
    )
    return dispatcher


class DummyModelAdapter(BaseModelAdapter):
    async def complete(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        intent = TaskIntent(
            verb=Verb.EXECUTE,
            resource="workspace.command",
            scope=Scope.WORKSPACE,
            parameters={"task": "deploy microservice"},
            desired_output="deployed service",
            normalized_utterance="deploy microservice",
        )
        yield StreamChunk(delta="I will handle this. ", finish_reason=None)
        yield StreamChunk(
            delta="",
            finish_reason="tool_calls",
            tool_calls=[
                ToolCallPart(
                    id="call_deploy",
                    name="fulfill_request",
                    arguments=intent.model_dump_json(),
                )
            ],
        )


@pytest.mark.asyncio
async def test_triage_capability_gap_acknowledgment(
    mock_recipe_repo: MagicMock, mock_dispatcher: MagicMock
) -> None:
    signaler = MagicMock(spec=CompletionSignaler)
    pipeline = JobAssemblyPipeline(
        dispatcher=mock_dispatcher,
        signaler=signaler,
        recipe_repo=mock_recipe_repo,
    )

    report = pipeline.triage_capability_gap("deploy microservice", ["shell_exec"])
    assert report.has_gap is True
    assert report.acknowledgment is not None
    assert "I don't have a saved recipe for 'deploy microservice' yet" in report.acknowledgment
    assert "assembling an on-the-fly task brief" in report.acknowledgment


@pytest.mark.asyncio
async def test_run_pipeline_triggers_on_status(
    mock_recipe_repo: MagicMock, mock_dispatcher: MagicMock
) -> None:
    signaler = MagicMock(spec=CompletionSignaler)
    pipeline = JobAssemblyPipeline(
        dispatcher=mock_dispatcher,
        signaler=signaler,
        recipe_repo=mock_recipe_repo,
    )

    status_messages: list[str] = []

    request = JobAssemblyRequest(
        session_id="sess_1",
        task="deploy microservice",
        available_tools=["shell_exec"],
    )
    res = await pipeline.run_pipeline(request, on_status=status_messages.append)
    assert len(status_messages) == 1
    assert "deploy microservice" in status_messages[0]
    assert res.dispatch_result.decision.stage == "assembled_ephemeral"


@pytest.mark.asyncio
async def test_chat_loop_yields_status_event_on_dynamic_job(
    mock_recipe_repo: MagicMock,
    mock_dispatcher: MagicMock,
) -> None:
    session_repo = MagicMock(spec=SessionRepository)
    session_repo.get_recent_turns.return_value = []
    session_repo.append_turn.return_value = TurnRecord(
        turn_id="turn_1",
        session_id="sess_1",
        turn_index=1,
        role="assistant",
        content="I will handle this. [DISPATCH: deploy microservice]",
        token_count=10,
    )
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    session_repo.ensure_session.return_value = SessionRecord(
        session_id="sess_1", title="Test", created_at=now, updated_at=now
    )

    pipeline = JobAssemblyPipeline(
        dispatcher=mock_dispatcher,
        signaler=MagicMock(spec=CompletionSignaler),
        recipe_repo=mock_recipe_repo,
    )

    async def mock_job_dispatcher(session_id: str, task: str, on_status=None):
        return await pipeline.run_pipeline(
            JobAssemblyRequest(
                session_id=session_id,
                task=task,
                available_tools=["shell_exec"],
            ),
            on_status=on_status,
        )

    chat_loop = CompanionChatLoop(
        session_id="sess_1",
        session_repo=session_repo,
        model_adapter=DummyModelAdapter(),
        config=CompanionConfig(name="Atlas"),
        job_dispatcher=mock_job_dispatcher,
    )

    events = [ev async for ev in chat_loop.execute_turn("Please deploy microservice")]
    status_events = [ev for ev in events if ev.event_type == "status"]
    assert len(status_events) >= 1
    assert "assembling an on-the-fly task brief" in status_events[0].delta
