"""Sandboxed recipe chamber and isolated worker process coordinator."""

from time import perf_counter
from typing import Literal

from agent_os.domain.ipc import SubJobExecutionRequest, SubJobReturnEnvelope
from agent_os.domain.policy import ActionTier
from agent_os.domain.runner import RunnerExecutionRequest
from agent_os.domain.tools import ToolDefinition
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.return_marshaller import SubJobMarshaller
from agent_os.kernel.runner import NativeRunner


class RecipeChamber:
    """Coordinates isolated sub-job execution within sandboxed journey scratchpads."""

    def __init__(self, runner: NativeRunner, session_repo: SessionRepository) -> None:
        self.runner = runner
        self.repo = session_repo

    async def execute_sub_job(self, request: SubJobExecutionRequest) -> SubJobReturnEnvelope:
        """Execute a sub-job task hermetically and record telemetry in the journey scratchpad."""
        # 1. Initialize journey in SQLite
        journey = self.repo.record_journey_start(
            session_id=request.session_id,
            task=request.task,
        )

        # 2. Construct runner execution request
        tools = [
            ToolDefinition(
                name=t_name,
                description=f"Target tool: {t_name}",
                action_tier=ActionTier.STATE_CHANGE,
            )
            for t_name in request.packet.target_tools
        ]
        runner_req = RunnerExecutionRequest(
            task=request.task,
            modality="react" if tools else "direct",
            system_prompt=request.packet.system_prompt,
            timeout_seconds=request.timeout_seconds,
            tools=tools,
        )

        # 3. Run execution with timing
        start_time = perf_counter()
        result = await self.runner.execute(runner_req)
        duration_ms = int((perf_counter() - start_time) * 1000)

        # 4. Persist each step event to SQLite journey scratchpad
        for step in result.steps:
            self.repo.record_journey_step(
                journey_id=journey.journey_id,
                node_name=step.step_type,
                input_payload=step.tool_input,
                output_payload={"output": step.tool_output or ""},
                duration_ms=step.duration_ms,
            )

        # 5. Determine terminal status
        status: Literal["completed", "failed", "aborted"]
        if result.aborted_by_cycle_detection:
            status = "aborted"
        elif result.success:
            status = "completed"
        else:
            status = "failed"

        summary_text = (
            result.final_output
            if result.success
            else (result.error or result.final_output or "Execution failed")
        )

        # 6. Complete journey in SQLite
        self.repo.complete_journey(
            journey_id=journey.journey_id,
            status=status,
            summary=summary_text,
            artifacts=[],
            state_mutations=[],
            metrics={"duration_ms": duration_ms, "total_turns": result.total_turns},
        )

        # 7. Marshal and return bounded envelope
        # Context isolation invariant: session turns are NEVER modified with worker steps.
        return SubJobMarshaller.marshal_envelope(
            journey_id=journey.journey_id,
            status=status,
            raw_output=summary_text,
            artifact_paths=[],
            state_mutations=[],
            duration_ms=duration_ms,
        )
