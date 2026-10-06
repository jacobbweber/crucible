"""End-to-end dynamic job assembly line and execution pipeline orchestrator."""

from agent_os.domain.pipeline import (
    CapabilityGapReport,
    JobAssemblyRequest,
    PipelineExecutionResult,
)
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.signaling import CompletionSignaler


class JobAssemblyPipeline:
    """Coordinates capability gap triage, dynamic zero-catalog dispatch, and signaling."""

    def __init__(
        self,
        dispatcher: ZeroCatalogDispatcher,
        signaler: CompletionSignaler,
        recipe_repo: RecipeRepository,
    ) -> None:
        self.dispatcher = dispatcher
        self.signaler = signaler
        self.recipe_repo = recipe_repo

    def triage_capability_gap(self, task: str, available_tools: list[str]) -> CapabilityGapReport:
        """Triage whether a task can be satisfied by catalog recipes or requires synthesis."""
        matches = self.recipe_repo.match_intent(task, limit=1)
        threshold = getattr(self.dispatcher, "threshold", 0.5)

        is_match = False
        top_recipe = None
        if matches and matches[0].score >= threshold:
            is_match = True
            top_recipe = matches[0].recipe

        if is_match and top_recipe is not None:
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
            )

        return CapabilityGapReport(
            task=task,
            missing_capabilities=[],
            has_gap=True,
            resolution_strategy="ephemeral_synthesis",
        )

    async def run_pipeline(self, request: JobAssemblyRequest) -> PipelineExecutionResult:
        """Execute end-to-end job assembly, dispatch, signaling, and graduation triage."""
        # 1. Assess capability gaps
        gap_report = self.triage_capability_gap(request.task, request.available_tools)

        # 2. Dispatch execution via ZeroCatalogDispatcher
        dispatch_res = await self.dispatcher.dispatch_task(
            request.session_id,
            request.task,
            available_tools=request.available_tools,
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
