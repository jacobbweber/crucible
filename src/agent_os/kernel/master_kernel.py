"""Master orchestration kernel coordinating all agent-os runtime subsystems."""

import inspect
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.dispatch import DispatchResult
from agent_os.domain.kernel import KernelConfig, TurnResponse, UserTurnRequest
from agent_os.domain.pipeline import JobAssemblyRequest, PipelineExecutionResult
from agent_os.domain.policy import (
    ActionTier,
    ApprovalMode,
    PolicyDecisionType,
    ToolCallRequest,
)
from agent_os.domain.schedule import RoutineExecutionLog
from agent_os.domain.tools import ToolExecutionResult
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.infrastructure.security.vault_repo import CredentialVaultRepository
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.infrastructure.storage.facts_repo import FactRepository
from agent_os.infrastructure.storage.recipe_repo import RecipeRepository
from agent_os.infrastructure.storage.session_db import get_connection
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.infrastructure.wiki.store import WikiStore
from agent_os.kernel.chat_loop import CompanionChatLoop
from agent_os.kernel.credential_proxy import CredentialProxyGate
from agent_os.kernel.dispatcher import ZeroCatalogDispatcher
from agent_os.kernel.education_tools import EducationToolSuite
from agent_os.kernel.fact_prefetcher import FactPrefetcher
from agent_os.kernel.pipeline import JobAssemblyPipeline
from agent_os.kernel.policy_gate import ToolPolicyGate
from agent_os.kernel.recipe_chamber import RecipeChamber
from agent_os.kernel.runner import NativeRunner
from agent_os.kernel.scheduler import EmbeddedSchedulerDaemon
from agent_os.kernel.signaling import CompletionSignaler
from agent_os.kernel.srs_engine import SRSEngine
from agent_os.kernel.wiki_tools import WikiToolSuite


class _SchedulerSignalingDispatcher:
    """Wraps ZeroCatalogDispatcher for background routines to signal completion."""

    def __init__(
        self,
        dispatcher: ZeroCatalogDispatcher,
        signaler: CompletionSignaler,
        session_repo: SessionRepository,
    ) -> None:
        self._dispatcher = dispatcher
        self._signaler = signaler
        self._session_repo = session_repo

    async def dispatch_task(
        self,
        session_id: str,
        task: str,
        available_tools: list[str] | None = None,
    ) -> DispatchResult:
        if not self._session_repo.get_session(session_id):
            now = datetime.now(UTC)
            now_str = now.isoformat()
            with get_connection(self._session_repo.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (
                        session_id, title, created_at, updated_at, is_archived
                    ) VALUES (?, ?, ?, ?, 0);
                    """,
                    (session_id, f"System Session: {session_id}", now_str, now_str),
                )
        res = await self._dispatcher.dispatch_task(
            session_id, task, available_tools=available_tools
        )
        self._signaler.signal_completion(session_id, res.envelope)
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._dispatcher, name)


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
    ) -> None:
        self.config = config
        self.session_repo = session_repo
        self.facts_repo = facts_repo
        self.recipe_repo = recipe_repo
        self.education_repo = education_repo
        self.vault_repo = vault_repo
        self.wiki_store = wiki_store
        self.model_adapter = model_adapter

        # Core subsystems
        self.semaphore = InferenceSemaphore(max_concurrency=config.max_concurrency)
        self.policy_gate = ToolPolicyGate(approval_mode=ApprovalMode(config.approval_mode))
        self.credential_proxy = CredentialProxyGate(vault_repo=vault_repo)
        self.wiki_tools = WikiToolSuite(wiki_store=wiki_store)
        self.srs_engine = SRSEngine()
        self.education_tools = EducationToolSuite(
            education_repo=education_repo, srs_engine=self.srs_engine
        )

        # Tools registration
        self.tools: dict[str, Callable[..., Any]] = {}
        self._tool_tiers: dict[str, ActionTier] = {}
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
        self.chamber = RecipeChamber(runner=self.runner, session_repo=session_repo)

        # Signaling & Dispatch
        self.signaler = CompletionSignaler()
        self.dispatcher = ZeroCatalogDispatcher(
            recipe_repo=recipe_repo,
            recipe_chamber=self.chamber,
            model_adapter=model_adapter,
        )
        self.assembly_pipeline = JobAssemblyPipeline(
            dispatcher=self.dispatcher,
            signaler=self.signaler,
            recipe_repo=recipe_repo,
        )

        # Scheduler with completion signaling
        signaling_sched_dispatcher = _SchedulerSignalingDispatcher(
            dispatcher=self.dispatcher,
            signaler=self.signaler,
            session_repo=self.session_repo,
        )
        self.scheduler = EmbeddedSchedulerDaemon(
            dispatcher=signaling_sched_dispatcher,  # type: ignore[arg-type]
            semaphore=self.semaphore,
        )

        # Fact prefetcher
        self.fact_prefetcher = FactPrefetcher(facts_repo=facts_repo)

    def _register_default_tools(self) -> None:
        """Register built-in wiki and education tools."""
        for defn in self.wiki_tools.get_definitions():
            fn = getattr(self.wiki_tools, defn.name, None)
            if fn:
                self.register_tool(defn.name, fn, defn.action_tier)

        for defn in self.education_tools.get_definitions():
            fn = getattr(self.education_tools, defn.name, None)
            if fn:
                self.register_tool(defn.name, fn, defn.action_tier)

    def register_tool(
        self,
        name: str,
        fn: Callable[..., Any],
        action_tier: ActionTier = ActionTier.STATE_CHANGE,
    ) -> None:
        """Register a new tool into the kernel execution and dispatch registry."""
        self.tools[name] = fn
        self._tool_tiers[name] = action_tier
        self.tool_dispatcher[name] = self._make_tool_invoker(name, fn)

    def _make_tool_invoker(
        self, tool_name: str, fn: Callable[..., Any]
    ) -> Callable[..., Coroutine[Any, Any, ToolExecutionResult]]:
        """Create an async invoker wrapping parameter unmasking and output scrubbing."""

        async def _invoker(**kwargs: Any) -> ToolExecutionResult:
            resolved = self.credential_proxy.resolve_parameters(kwargs)
            try:
                res = fn(**resolved.resolved_params)
                if inspect.iscoroutine(res):
                    tool_res: ToolExecutionResult = await res
                elif isinstance(res, ToolExecutionResult):
                    tool_res = res
                else:
                    tool_res = ToolExecutionResult(
                        tool_name=tool_name,
                        success=True,
                        output=str(res),
                    )
            except Exception as e:
                tool_res = ToolExecutionResult(
                    tool_name=tool_name,
                    success=False,
                    output="",
                    error=str(e),
                )

            if resolved.secrets_to_scrub and tool_res.output:
                scrubbed = self.credential_proxy.scrub_text(
                    tool_res.output, resolved.secrets_to_scrub
                )
                tool_res = ToolExecutionResult(
                    tool_name=tool_name,
                    success=tool_res.success,
                    output=scrubbed.sanitized_text,
                    error=tool_res.error,
                )
            return tool_res

        return _invoker

    async def execute_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any] | None = None,
    ) -> ToolExecutionResult:
        """Execute a tool through the full policy gate, credential proxy, and scrubbing stack."""
        params = parameters or {}
        tier = self._tool_tiers.get(tool_name, ActionTier.DESTRUCTIVE)
        decision = self.policy_gate.evaluate(
            ToolCallRequest(
                tool_name=tool_name,
                parameters=params,
                action_tier=tier,
            )
        )
        if decision.decision == PolicyDecisionType.BLOCK or decision.requires_prompt:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"Blocked by policy gate: {decision.reason or 'Action rejected'}",
            )

        if tool_name not in self.tool_dispatcher:
            return ToolExecutionResult(
                tool_name=tool_name,
                success=False,
                output="",
                error=f"Tool '{tool_name}' not found",
            )

        invoker = self.tool_dispatcher[tool_name]
        return await invoker(**params)

    async def handle_user_turn(self, request: UserTurnRequest) -> TurnResponse:
        """Handle an interactive user turn with prefetching, background drain, and streaming."""
        # 1. Pre-fetch facts
        facts_payload = self.fact_prefetcher.prefetch_for_turn(request.user_input)

        # 2. Drain background completions
        deferred_block = self.signaler.format_deferred_prompt_block(request.session_id)

        # 3. Companion chat loop with combined prompt facts hook
        chat_loop = CompanionChatLoop(
            session_id=request.session_id,
            session_repo=self.session_repo,
            model_adapter=self.model_adapter,
            config=CompanionConfig(name=self.config.companion_name),
        )

        # 4. Stream and accumulate events
        events = []
        response_parts: list[str] = []
        final_turn_content = ""

        async for event in chat_loop.execute_turn(
            user_input=request.user_input,
            recalled_facts_block=facts_payload.rendered_block,
            background_completions_block=deferred_block,
        ):
            events.append(event)
            if event.event_type == "delta":
                response_parts.append(event.delta)
            elif event.event_type == "completed" and event.turn:
                final_turn_content = event.turn.content

        response_text = "".join(response_parts) or final_turn_content

        # 5. Poll any newly generated ambient nudges
        nudges = self.signaler.poll_ambient_nudges()

        # 6. Return TurnResponse
        return TurnResponse(
            session_id=request.session_id,
            response_text=response_text,
            stream_events=events,
            recalled_facts_count=facts_payload.recalled_count,
            ambient_nudges=nudges,
        )

    async def execute_job(self, session_id: str, task: str) -> PipelineExecutionResult:
        """Dispatch background task execution through dynamic job assembly line."""
        return await self.assembly_pipeline.run_pipeline(
            JobAssemblyRequest(
                session_id=session_id,
                task=task,
                available_tools=list(self.tools.keys()),
            )
        )

    async def trigger_scheduler_tick(self, now: datetime) -> list[RoutineExecutionLog]:
        """Trigger background scheduler tick and return execution audit logs."""
        return await self.scheduler.tick(now)
