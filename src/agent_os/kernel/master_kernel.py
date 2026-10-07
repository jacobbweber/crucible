"""Master orchestration kernel coordinating all agent-os runtime subsystems."""

import inspect
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import datetime
from typing import Any

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.kernel import KernelConfig, TurnResponse, UserTurnRequest
from agent_os.domain.pipeline import JobAssemblyRequest, PipelineExecutionResult
from agent_os.domain.policy import (
    ActionTier,
    ApprovalMode,
    PolicyDecisionType,
    ToolCallRequest,
)
from agent_os.domain.schedule import RoutineExecutionLog
from agent_os.domain.tools import ToolDefinition, ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.routine_repo import RoutineRepository
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.storage.telemetry_repo import TelemetryRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.capability_scout import CapabilityScout
from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.credential_proxy import CredentialProxyGate
from agent_os.kernel.default_recipes import ensure_default_recipes
from agent_os.kernel.default_routines import ensure_default_routines
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.education_tools import EducationToolSuite
from agent_os.kernel.fact_prefetcher import FactPrefetcher
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.rca_stager import RcaProposalStager
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.runner import NativeRunner
from agent_os.kernel.scheduler import EmbeddedSchedulerDaemon
from agent_os.kernel.scheduler_dispatcher import SchedulerSignalingDispatcher
from agent_os.kernel.session_tools import SessionToolSuite
from agent_os.kernel.signaling import CompletionSignaler
from agent_os.kernel.srs_engine import SRSEngine
from agent_os.kernel.telemetry_collector import TelemetryCollector
from agent_os.kernel.telemetry_tools import TelemetryToolSuite
from agent_os.kernel.wiki_tools import WikiToolSuite


class AgentOSKernel:
    """Master orchestration kernel integrating conversational front-door and sandboxed workers."""

    def __init__(
        self,
        config: KernelConfig,
        session_repo: SessionRepository,
        facts_repo: FactRepository,
        recipe_repo: RecipeRepository,
        education_repo: EducationRepository,
        vault_repo: CredentialVaultRepository,
        wiki_store: WikiStore,
        model_adapter: BaseModelAdapter,
        semaphore: InferenceSemaphore | None = None,
        routine_repo: RoutineRepository | None = None,
        telemetry_repo: TelemetryRepository | None = None,
    ) -> None:
        self.config = config
        self.session_repo = session_repo
        self.facts_repo = facts_repo
        self.recipe_repo = recipe_repo
        self.education_repo = education_repo
        self.vault_repo = vault_repo
        self.wiki_store = wiki_store
        self.model_adapter = model_adapter
        self.routine_repo = routine_repo or RoutineRepository(session_repo.db_path)
        self.telemetry_repo = telemetry_repo or TelemetryRepository(
            session_repo.db_path.parent / "telemetry.db"
        )
        self.rca_stager = RcaProposalStager(wiki_store=wiki_store)
        self.collector = TelemetryCollector(self.telemetry_repo)
        self.signaler = CompletionSignaler()

        # Core subsystems
        self.semaphore = semaphore or InferenceSemaphore(max_concurrency=config.max_concurrency)
        self.policy_gate = ToolPolicyGate(approval_mode=ApprovalMode(config.approval_mode))
        self.credential_proxy = CredentialProxyGate(vault_repo=vault_repo)
        self.wiki_tools = WikiToolSuite(wiki_store=wiki_store)
        self.srs_engine = SRSEngine()
        self.education_tools = EducationToolSuite(
            education_repo=education_repo, srs_engine=self.srs_engine
        )
        self.session_tools = SessionToolSuite(session_repo=session_repo)
        self.telemetry_tools = TelemetryToolSuite(
            self.telemetry_repo, self.rca_stager, collector=self.collector, signaler=self.signaler
        )

        # Tools registration
        self.tools: dict[str, Callable[..., Any]] = {}
        self._tool_tiers: dict[str, ActionTier] = {}
        self._tool_definitions: dict[str, ToolDefinition] = {}
        self.tool_dispatcher: dict[
            str, Callable[..., Coroutine[Any, Any, ToolExecutionResult]]
        ] = {}

        self._register_default_tools()

        # Runner & Chamber
        self.runner = NativeRunner(
            model_adapter=model_adapter,
            policy_gate=self.policy_gate,
            tool_dispatcher=self.tool_dispatcher,
        )
        self.chamber = RecipeChamber(
            runner=self.runner,
            session_repo=session_repo,
            tool_tiers=self._tool_tiers,
            tool_definitions=self._tool_definitions,
        )

        # Signaling & Dispatch
        self.dispatcher = ZeroCatalogDispatcher(
            recipe_repo=recipe_repo,
            recipe_chamber=self.chamber,
            model_adapter=model_adapter,
        )
        self.capability_scout = CapabilityScout(wiki_store=self.wiki_store)
        self.assembly_pipeline = JobAssemblyPipeline(
            dispatcher=self.dispatcher,
            signaler=self.signaler,
            recipe_repo=recipe_repo,
            capability_scout=self.capability_scout,
        )

        # Scheduler with completion signaling and persistence (H6)
        signaling_sched_dispatcher = SchedulerSignalingDispatcher(
            dispatcher=self.dispatcher,
            signaler=self.signaler,
            session_repo=self.session_repo,
            tools=self.tools,
        )
        self.scheduler = EmbeddedSchedulerDaemon(
            dispatcher=signaling_sched_dispatcher,  # type: ignore[arg-type]
            semaphore=self.semaphore,
            routine_repo=self.routine_repo,
        )
        ensure_default_routines(self.routine_repo)
        ensure_default_recipes(self.recipe_repo)

        # Fact prefetcher
        self.fact_prefetcher = FactPrefetcher(facts_repo=facts_repo)

    def _register_default_tools(self) -> None:
        """Register built-in wiki, education, telemetry, and session tools."""
        suites = (
            self.wiki_tools,
            self.education_tools,
            self.telemetry_tools,
            self.session_tools,
        )
        for suite in suites:
            for defn in suite.get_definitions():
                fn = getattr(suite, defn.name, None)
                if fn:
                    self.register_tool(defn.name, fn, defn.action_tier, definition=defn)

    def register_tool(
        self,
        name: str,
        fn: Callable[..., Any],
        action_tier: ActionTier = ActionTier.STATE_CHANGE,
        definition: ToolDefinition | None = None,
    ) -> None:
        """Register a new tool into the kernel execution and dispatch registry."""
        self.tools[name] = fn
        self._tool_tiers[name] = action_tier
        self._tool_definitions[name] = definition or ToolDefinition(
            name=name, description=f"Tool: {name}", action_tier=action_tier
        )
        self.tool_dispatcher[name] = self._make_tool_invoker(name, fn)

    def _make_tool_invoker(
        self, tool_name: str, fn: Callable[..., Any]
    ) -> Callable[..., Coroutine[Any, Any, ToolExecutionResult]]:
        """Create an async invoker wrapping parameter unmasking and output scrubbing."""

        async def _invoker(**kwargs: Any) -> ToolExecutionResult:
            resolved = self.credential_proxy.resolve_parameters(kwargs)
            try:
                res = fn(**resolved.resolved_params)
                tool_res = await res if inspect.iscoroutine(res) else res
                if not isinstance(tool_res, ToolExecutionResult):
                    tool_res = ToolExecutionResult(
                        tool_name=tool_name, success=True, output=str(res)
                    )
            except Exception as e:
                tool_res = ToolExecutionResult(
                    tool_name=tool_name, success=False, output="", error=str(e)
                )

            output, error = tool_res.output, tool_res.error
            if resolved.secrets_to_scrub:
                s = resolved.secrets_to_scrub
                if output:
                    output = self.credential_proxy.scrub_text(output, s).sanitized_text
                if error:
                    error = self.credential_proxy.scrub_text(error, s).sanitized_text

            return ToolExecutionResult(
                tool_name=tool_name, success=tool_res.success, output=output, error=error
            )

        return _invoker

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, Any] | None = None
    ) -> ToolExecutionResult:
        """Execute a tool through policy gate, credential proxy, and scrubbing stack."""
        params = parameters or {}
        tier = self._tool_tiers.get(tool_name, ActionTier.DESTRUCTIVE)
        decision = self.policy_gate.evaluate(
            ToolCallRequest(tool_name=tool_name, parameters=params, action_tier=tier)
        )
        if decision.decision == PolicyDecisionType.BLOCK or decision.requires_prompt:
            err = f"Blocked by policy gate: {decision.reason or 'Action rejected'}"
            return ToolExecutionResult(tool_name=tool_name, success=False, output="", error=err)
        if tool_name not in self.tool_dispatcher:
            return ToolExecutionResult(
                tool_name=tool_name, success=False, output="", error=f"Tool '{tool_name}' not found"
            )
        return await self.tool_dispatcher[tool_name](**params)

    async def stream_user_turn(self, request: UserTurnRequest) -> AsyncIterator[StreamTurnEvent]:
        """Stream an interactive user turn progressively (K1)."""
        facts_payload = self.fact_prefetcher.prefetch_for_turn(request.user_input)
        deferred_block = self.signaler.format_deferred_prompt_block(request.session_id)
        chat_loop = CompanionChatLoop(
            session_id=request.session_id,
            session_repo=self.session_repo,
            model_adapter=self.model_adapter,
            config=CompanionConfig(name=self.config.companion_name),
            context_window=self.config.context_window,
            reserve_output_tokens=self.config.reserve_output_tokens,
            job_dispatcher=self.execute_job,
            tool_dispatcher=self.execute_tool,
        )
        async for event in chat_loop.execute_turn(
            user_input=request.user_input,
            recalled_facts_block=facts_payload.rendered_block,
            background_completions_block=deferred_block,
        ):
            yield event

    async def handle_user_turn(self, request: UserTurnRequest) -> TurnResponse:
        """Handle an interactive user turn with prefetching, background drain, and streaming."""
        facts_payload = self.fact_prefetcher.prefetch_for_turn(request.user_input)
        events: list[StreamTurnEvent] = []
        response_parts: list[str] = []
        dispatched_subjobs: list[PipelineExecutionResult] = []
        final_turn_content = ""
        last_error = ""

        async for event in self.stream_user_turn(request):
            events.append(event)
            if event.event_type == "delta":
                response_parts.append(event.delta)
            elif event.event_type == "job_dispatched":
                if isinstance(event.dispatched_job, PipelineExecutionResult):
                    dispatched_subjobs.append(event.dispatched_job)
            elif event.event_type == "completed" and event.turn:
                final_turn_content = event.turn.content
            elif event.event_type == "error":
                last_error = event.error_message or "Unknown error"

        response_text = "".join(response_parts) or final_turn_content
        if not response_text and last_error:
            response_text = f"Error during turn: {last_error}"

        return TurnResponse(
            session_id=request.session_id,
            response_text=response_text,
            stream_events=events,
            recalled_facts_count=facts_payload.recalled_count,
            dispatched_subjobs=dispatched_subjobs,
            ambient_nudges=self.signaler.poll_ambient_nudges(session_id=request.session_id),
        )

    async def execute_job(
        self, session_id: str, task: str, on_status: Callable[[str], Any] | None = None
    ) -> PipelineExecutionResult:
        """Dispatch background task execution through dynamic job assembly line."""
        req = JobAssemblyRequest(
            session_id=session_id, task=task, available_tools=list(self.tools.keys())
        )
        return await self.assembly_pipeline.run_pipeline(req, on_status=on_status)

    async def trigger_scheduler_tick(self, now: datetime) -> list[RoutineExecutionLog]:
        """Trigger background scheduler tick and return execution audit logs."""
        return await self.scheduler.tick(now)
