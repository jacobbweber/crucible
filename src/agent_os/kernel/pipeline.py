import inspect
from collections.abc import Callable
from typing import Any

from agent_os.domain.pipeline import (
    CapabilityGapReport,
    JobAssemblyRequest,
    PipelineExecutionResult,
)
from agent_os.domain.recipe import RecipeMetadata, RecipeRecord
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.recipe_triage import select_best_recipe_match
from agent_os.kernel.signaling import CompletionSignaler


class JobAssemblyPipeline:
    """Coordinates capability gap triage, dynamic zero-catalog dispatch, and signaling."""

    def __init__(
        self,
        dispatcher: ZeroCatalogDispatcher,
        signaler: CompletionSignaler,
        recipe_repo: RecipeRepository,
        capability_scout: Any | None = None,
        toolsmith: Any | None = None,
        on_activate_tool: Callable[[str], Any] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.signaler = signaler
        self.recipe_repo = recipe_repo
        self.capability_scout = capability_scout
        self.toolsmith = toolsmith
        self.on_activate_tool = on_activate_tool

    def triage_capability_gap(self, task: str, available_tools: list[str]) -> CapabilityGapReport:
        """Triage whether a task can be satisfied by catalog recipes or requires synthesis."""
        matches = self.recipe_repo.match_intent(task, limit=5)
        threshold = getattr(self.dispatcher, "threshold", 0.5)
        best_match = select_best_recipe_match(task, matches, threshold)

        ack_message = (
            f"I don't have a saved recipe for '{task}' yet. "
            "I'm assembling an on-the-fly task brief and selecting the right tools now..."
        )

        if best_match is not None:
            top_recipe = best_match.recipe
            available_set = set(available_tools)
            required = top_recipe.metadata.required_tools
            missing = [tool for tool in required if tool not in available_set]
            if not missing:
                return CapabilityGapReport(
                    task=task,
                    missing_capabilities=[],
                    has_gap=False,
                    resolution_strategy="none",
                )
            return CapabilityGapReport(
                task=task,
                missing_capabilities=missing,
                has_gap=True,
                resolution_strategy="ephemeral_synthesis",
                acknowledgment=ack_message,
            )

        return CapabilityGapReport(
            task=task,
            missing_capabilities=[],
            has_gap=True,
            resolution_strategy="ephemeral_synthesis",
            acknowledgment=ack_message,
        )

    async def run_pipeline(
        self,
        request: JobAssemblyRequest,
        on_status: Callable[[str], Any] | None = None,
    ) -> PipelineExecutionResult:
        """Execute end-to-end job assembly, dispatch, signaling, and graduation triage."""
        # 1. Assess capability gaps
        gap_report = self.triage_capability_gap(request.task, request.available_tools)
        if gap_report.has_gap and gap_report.acknowledgment and on_status is not None:
            res = on_status(gap_report.acknowledgment)
            if inspect.iscoroutine(res):
                await res

        # 1b. Check if task targets an external domain missing from available tools
        if (self.capability_scout or self.toolsmith) and gap_report.has_gap:
            missing_domain = None
            if self.capability_scout:
                if hasattr(self.capability_scout, "evaluate_missing_domain"):
                    missing_domain = await self.capability_scout.evaluate_missing_domain(
                        request.task, request.available_tools
                    )
                else:
                    missing_domain = self.capability_scout.identify_missing_domain(
                        request.task, request.available_tools
                    )

            if missing_domain:
                if self.toolsmith:
                    if on_status is not None:
                        res = on_status(f"Synthesizing capability for '{missing_domain}' in scratch workspace...")
                        if inspect.iscoroutine(res):
                            await res
                    from agent_os.domain.toolsmith import ToolsmithSynthesisRequest

                    synth_req = ToolsmithSynthesisRequest(task=request.task, domain=missing_domain, available_tools=request.available_tools)
                    prop = await self.toolsmith.synthesize_and_verify(synth_req)
                    staged_path = prop.staged_path

                    if prop.verified and self.on_activate_tool is not None:
                        if on_status is not None:
                            res = on_status(f"Verified tool '{prop.tool_name}'. Mounting into live runtime...")
                            if inspect.iscoroutine(res):
                                await res
                        try:
                            new_tools = await self.on_activate_tool(prop.tool_name)
                            mounted_tool_names = [t.name for t in new_tools]
                            clean_names = [t.name.removeprefix("mcp_hub_") for t in new_tools if t.name.startswith("mcp_hub_")]
                            all_new = mounted_tool_names + clean_names
                            updated_tools = list(set(request.available_tools + all_new))

                            if on_status is not None:
                                res = on_status(f"Executing directive with active tool '{prop.tool_name}'...")
                                if inspect.iscoroutine(res):
                                    await res

                            dispatch_res = await self.dispatcher.dispatch_task(
                                request.session_id,
                                request.task,
                                available_tools=updated_tools,
                                timeout_seconds=request.timeout_seconds,
                                context_payload=request.context_payload,
                            )
                            self.signaler.signal_completion(request.session_id, dispatch_res.envelope)
                            return PipelineExecutionResult(
                                session_id=request.session_id,
                                task=request.task,
                                dispatch_result=dispatch_res,
                                gap_report=gap_report,
                                flagged_for_graduation=True,
                            )
                        except Exception as mount_err:
                            if on_status is not None:
                                res = on_status(f"Tool mounting encountered: {mount_err}. Falling back to proposal.")
                                if inspect.iscoroutine(res):
                                    await res

                    if prop.verified:
                        summary = (
                            f"[TOOL_PROPOSAL: {prop.tool_name}] Verified via pre-flight dry run. "
                            f"Output: '{prop.dry_run_output}'. Ready for mounting."
                        )
                    else:
                        summary = f"Tool synthesis for '{missing_domain}' failed dry run: {prop.error_message}"
                else:
                    if on_status is not None:
                        res = on_status(f"Detected missing capability '{missing_domain}'. Staging proposal...")
                        if inspect.iscoroutine(res):
                            await res
                    staged_path = self.capability_scout.stage_mcp_proposal(request.task, missing_domain)
                    summary = f"Missing tool for '{missing_domain}'. Prepared capability proposal in {staged_path}."

                from agent_os.domain.dispatch import DispatchDecision, DispatchResult
                from agent_os.domain.ipc import SubJobReturnEnvelope

                envelope = SubJobReturnEnvelope(
                    journey_id=f"gap_{request.session_id}",
                    status="completed",
                    summary=summary,
                    artifact_paths=[staged_path] if staged_path else [],
                    token_estimate=50,
                )
                dispatch_res = DispatchResult(
                    decision=DispatchDecision(task=request.task, stage="assembled_ephemeral"),
                    envelope=envelope,
                )
                self.signaler.signal_completion(request.session_id, envelope)
                return PipelineExecutionResult(
                    session_id=request.session_id,
                    task=request.task,
                    dispatch_result=dispatch_res,
                    gap_report=gap_report,
                    flagged_for_graduation=False,
                )


        # 2. Dispatch execution via ZeroCatalogDispatcher
        dispatch_res = await self.dispatcher.dispatch_task(
            request.session_id,
            request.task,
            available_tools=request.available_tools,
            timeout_seconds=request.timeout_seconds,
            context_payload=request.context_payload,
        )


        # 3. Channel Signaling
        self.signaler.signal_completion(request.session_id, dispatch_res.envelope)

        # 4. Ephemeral Graduation Triage (ADR-014)
        flagged_for_graduation = (
            dispatch_res.decision.stage == "assembled_ephemeral"
            and dispatch_res.envelope.status == "completed"
        )

        # 5. Return aggregated pipeline execution result
        return PipelineExecutionResult(
            session_id=request.session_id,
            task=request.task,
            dispatch_result=dispatch_res,
            gap_report=gap_report,
            flagged_for_graduation=flagged_for_graduation,
        )

    def graduate_ephemeral_job(
        self,
        result: PipelineExecutionResult,
        recipe_id: str,
        name: str,
        description: str,
        tags: list[str] | None = None,
    ) -> RecipeRecord:
        """Promote a successful ephemeral job into a persistent catalog recipe (ADR-014)."""
        if not result.flagged_for_graduation:
            raise ValueError("Pipeline result is not eligible for graduation")

        tags_list = tags or ["graduated", "ephemeral"]
        record = RecipeRecord(
            metadata=RecipeMetadata(
                recipe_id=recipe_id,
                name=name,
                description=description,
                execution_engine="react",
                target_model_tier="reasoning",
                tags=tags_list,
                required_tools=result.dispatch_result.decision.ephemeral_tools,
                timeout_seconds=300,
            ),
            markdown_path=f"recipes/{recipe_id}.md",
            body=result.dispatch_result.envelope.summary,
        )
        return self.recipe_repo.upsert_recipe(record)
