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

    def __init__(
        self,
        runner: NativeRunner,
        session_repo: SessionRepository,
        tool_tiers: dict[str, ActionTier] | None = None,
        tool_definitions: dict[str, ToolDefinition] | None = None,
        default_tier: ActionTier | None = None,
    ) -> None:
        self.runner = runner
        self.repo = session_repo
        self.tool_tiers = tool_tiers if tool_tiers is not None else {}
        self.tool_definitions = tool_definitions if tool_definitions is not None else {}
        self._default_tier = (
            default_tier
            if default_tier is not None
            else (ActionTier.DESTRUCTIVE if tool_tiers is not None else ActionTier.STATE_CHANGE)
        )

    async def execute_sub_job(self, request: SubJobExecutionRequest) -> SubJobReturnEnvelope:
        """Execute a sub-job task hermetically and record telemetry in the journey scratchpad."""
        # 1. Initialize journey in SQLite
        journey = self.repo.record_journey_start(
            session_id=request.session_id,
            task=request.task,
        )

        # 2. Context assembly and pre-flight verification
        context_data = (request.context_payload or "").strip()
        if not context_data and hasattr(self.repo, "get_recent_turns"):
            recent_turns = self.repo.get_recent_turns(request.session_id, limit=3)
            if recent_turns:
                context_data = "\n\n".join(
                    f"[{t.role.upper()}]:\n{t.content.strip()}"
                    for t in recent_turns
                    if t.content.strip()
                )

        effective_task = request.task
        if context_data:
            effective_task = (
                f"{request.task}\n\n"
                f"### Context Data & Reference Conversation Payload:\n"
                f"{context_data}"
            )

        target_tools = list(request.packet.target_tools)
        task_lower = request.task.lower()
        if any(w in task_lower for w in ("save", "write", "capture", "store")) and "warehouse" in task_lower:
            if "warehouse_write" not in target_tools and ("warehouse_write" in self.tool_definitions or "warehouse_write" in self.tool_tiers):
                target_tools.append("warehouse_write")
            if "warehouse_read" not in target_tools and ("warehouse_read" in self.tool_definitions or "warehouse_read" in self.tool_tiers):
                target_tools.append("warehouse_read")

        # 3. Construct runner execution request
        tools: list[ToolDefinition] = []
        for t_name in target_tools:
            if t_name in self.tool_definitions:
                tools.append(self.tool_definitions[t_name])
            elif t_name in self.tool_tiers:
                tools.append(
                    ToolDefinition(
                        name=t_name,
                        description=f"Target tool: {t_name}",
                        action_tier=self.tool_tiers[t_name],
                    )
                )
            else:
                tools.append(
                    ToolDefinition(
                        name=t_name,
                        description=f"Target tool: {t_name}",
                        action_tier=self._default_tier,
                    )
                )
        modality = request.packet.modality or ("react" if tools else "direct")
        runner_req = RunnerExecutionRequest(
            task=effective_task,
            modality=modality,
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
