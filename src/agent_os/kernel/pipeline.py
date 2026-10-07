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

        ack_message = (
            f"I don't have a saved recipe for '{task}' yet. "
            "I'm assembling an on-the-fly task brief and selecting the right tools now..."
        )

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

        # 2. Dispatch execution via ZeroCatalogDispatcher
        dispatch_res = await self.dispatcher.dispatch_task(
            request.session_id,
            request.task,
            available_tools=request.available_tools,
            timeout_seconds=request.timeout_seconds,
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
