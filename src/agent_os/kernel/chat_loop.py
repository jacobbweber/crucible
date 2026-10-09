"""Interactive companion session orchestrator managing turns and context sliding window."""

import asyncio
import inspect
import json
import re
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import ChatSessionState, StreamTurnEvent
from agent_os.domain.gateway import (
    ChatMessage,
    CompletionRequest,
    ToolCallPart,
    ToolSpec,
    estimate_tokens,
)
from agent_os.domain.ingredients.vocabulary import ResourceVocabularyRegistry
from agent_os.domain.session import TurnRecord
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.companion_front_door import (
    build_fulfill_request_tool_spec,
    parse_task_intent,
)
from agent_os.kernel.prompt_assembler import PromptAssembler


def extract_dispatch_directives(text: str) -> list[str]:
    """Legacy utility: extract [DISPATCH: <task>] directives from text."""
    matches = re.findall(r"\[DISPATCH:\s*(.+?)\]", text, flags=re.DOTALL | re.IGNORECASE)
    return [m.strip() for m in matches if m.strip()]


def extract_tool_directives(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Legacy utility: extract [TOOL: <name> <json_params>] directives from text."""
    results: list[tuple[str, dict[str, Any]]] = []
    pattern = re.compile(r"\[TOOL:\s*([a-zA-Z0-9_\-]+)", re.IGNORECASE)
    for m in pattern.finditer(text):
        tool_name, pos = m.group(1).strip(), m.end()
        params: dict[str, Any] = {}
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos < len(text) and text[pos] == "{":
            depth, in_q, esc, start = 0, False, False, pos
            for i, ch in enumerate(text[start:], start=start):
                if esc:
                    esc = False
                    continue
                if ch == "\\":
                    esc = True
                    continue
                if ch == '"':
                    in_q = not in_q
                    continue
                if not in_q:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                parsed = json.loads(text[start : i + 1])
                                if isinstance(parsed, dict):
                                    params = parsed
                            except Exception:
                                pass
                            break
        results.append((tool_name, params))
    return results


class CompanionChatLoop:
    """Coordinates turn streaming, prompt assembly, and sliding window persistence."""

    def __init__(
        self,
        session_id: str,
        session_repo: SessionRepository,
        model_adapter: BaseModelAdapter,
        config: CompanionConfig,
        sliding_window_size: int = 15,
        target_model: str | None = None,
        context_window: int = 8192,
        reserve_output_tokens: int = 1024,
        job_dispatcher: (Callable[..., Coroutine[Any, Any, Any]] | None) = None,
        tool_dispatcher: (
            Callable[[str, dict[str, Any] | None], Coroutine[Any, Any, Any]] | None
        ) = None,
        vocabulary: ResourceVocabularyRegistry | None = None,
        tools: list[ToolSpec] | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_repo = session_repo
        self.repo = session_repo
        self.model_adapter = model_adapter
        self.adapter = model_adapter
        self.config = config
        self.sliding_window_size = sliding_window_size
        self.target_model = target_model
        self.context_window = context_window
        self.reserve_output_tokens = reserve_output_tokens
        self.job_dispatcher = job_dispatcher
        self.tool_dispatcher = tool_dispatcher
        self.assembler = PromptAssembler(config)
        self.vocabulary = vocabulary
        if tools is not None:
            self.tools = list(tools)
        else:
            self.tools = [build_fulfill_request_tool_spec(vocabulary)]

    def get_state(self) -> ChatSessionState:
        """Retrieve current session state with recent sliding window turns."""
        active_turns = self.session_repo.get_recent_turns(
            self.session_id, limit=self.sliding_window_size
        )
        if hasattr(self.session_repo, "count_turns"):
            total_turns = self.session_repo.count_turns(self.session_id)
        else:
            total_turns = len(active_turns)

        return ChatSessionState(
            session_id=self.session_id,
            active_turns=active_turns,
            sliding_window_size=self.sliding_window_size,
            total_turns_recorded=total_turns,
        )

    def _select_history_within_budget(
        self,
        user_turn_id: str,
        history_budget: int,
    ) -> list[ChatMessage]:
        """Select freshest turns respecting sliding window count and token budget (M5)."""
        recent_turns = self.session_repo.get_recent_turns(
            self.session_id, limit=self.sliding_window_size + 1
        )
        candidates = [t for t in recent_turns if t.turn_id != user_turn_id]
        selected: list[TurnRecord] = []
        used = 0
        for turn in reversed(candidates[-self.sliding_window_size :]):
            tok = turn.token_count if turn.token_count > 0 else estimate_tokens(turn.content)
            if used + tok > history_budget:
                break
            selected.append(turn)
            used += tok
        selected.reverse()
        return [ChatMessage(role=t.role, content=t.content) for t in selected]

    async def execute_turn(
        self,
        user_input: str,
        recalled_facts_block: str = "",
        background_completions_block: str = "",
    ) -> AsyncIterator[StreamTurnEvent]:
        """Execute a single conversational turn with streaming inference and persistence."""
        try:
            self.session_repo.ensure_session(self.session_id)
            user_tokens = estimate_tokens(user_input)
            user_turn = self.session_repo.append_turn(
                session_id=self.session_id,
                role="user",
                content=user_input,
                token_count=user_tokens,
            )

            assembled = self.assembler.assemble_system_prompt(
                recalled_facts_block=recalled_facts_block,
                background_completions_block=background_completions_block,
            )
            system_tokens = estimate_tokens(assembled.rendered_prompt)

            # Compute available history budget (context_window - output - system - user - margin)
            history_budget = max(
                0,
                self.context_window
                - self.reserve_output_tokens
                - system_tokens
                - user_tokens
                - 100,
            )
            history_messages = self._select_history_within_budget(user_turn.turn_id, history_budget)

            messages: list[ChatMessage] = [
                ChatMessage(role="system", content=assembled.rendered_prompt),
                *history_messages,
                ChatMessage(role="user", content=user_input),
            ]

            request = CompletionRequest(
                model=self.target_model,
                messages=messages,
                max_tokens=self.reserve_output_tokens,
                stream=True,
                tools=self.tools,
                tool_choice="auto",
            )

            accumulated_text_parts: list[str] = []
            accumulated_reasoning_parts: list[str] = []
            terminal_tool_calls: list[ToolCallPart] = []
            async for chunk in self.model_adapter.complete(request):
                if chunk.reasoning:
                    accumulated_reasoning_parts.append(chunk.reasoning)
                    yield StreamTurnEvent(
                        event_type="thinking",
                        reasoning=chunk.reasoning,
                        finish_reason=chunk.finish_reason,
                    )
                if chunk.delta:
                    accumulated_text_parts.append(chunk.delta)
                    yield StreamTurnEvent(
                        event_type="delta",
                        delta=chunk.delta,
                        finish_reason=chunk.finish_reason,
                    )
                if chunk.tool_calls:
                    terminal_tool_calls.extend(chunk.tool_calls)

            accumulated_text = "".join(accumulated_text_parts)
            completion_summaries: list[str] = []

            # 1. Native fulfill_request tool calls -> job_dispatcher
            fulfill_calls = [c for c in terminal_tool_calls if c.name == "fulfill_request"]
            if fulfill_calls and self.job_dispatcher:
                recent_turns = self.session_repo.get_recent_turns(self.session_id, limit=4)
                turn_parts = [
                    f"[{t.role.upper()}]:\n{t.content.strip()}"
                    for t in recent_turns
                    if t.turn_id != user_turn.turn_id and t.content.strip()
                ]
                turn_parts.append(f"[USER]:\n{user_input.strip()}")
                ctx_payload = "\n\n".join(turn_parts)

                for call in fulfill_calls:
                    try:
                        intent = parse_task_intent(call)
                    except Exception as exc:
                        yield StreamTurnEvent(
                            event_type="error",
                            error_message=f"Invalid task intent arguments: {exc}",
                        )
                        continue

                    try:
                        q: asyncio.Queue[str] = asyncio.Queue()
                        seen_status: set[str] = set()
                        sig = inspect.signature(self.job_dispatcher)
                        var_kw = any(
                            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                        )
                        kwargs: dict[str, Any] = {}
                        if var_kw or "on_status" in sig.parameters:
                            kwargs["on_status"] = q.put_nowait
                        if var_kw or "context_payload" in sig.parameters:
                            kwargs["context_payload"] = ctx_payload
                        if var_kw or "intent" in sig.parameters:
                            kwargs["intent"] = intent

                        fut = asyncio.create_task(
                            self.job_dispatcher(
                                self.session_id, intent.normalized_utterance, **kwargs
                            )
                        )

                        while not fut.done():
                            try:
                                msg = await asyncio.wait_for(q.get(), timeout=1.0)
                                seen_status.add(msg)
                                yield StreamTurnEvent(event_type="status", delta=msg)
                            except TimeoutError:
                                pass
                        job_res = await fut
                        while not q.empty():
                            msg = q.get_nowait()
                            seen_status.add(msg)
                            yield StreamTurnEvent(event_type="status", delta=msg)

                        gap_rep = getattr(job_res, "gap_report", None)
                        if gap_rep is not None and getattr(gap_rep, "has_gap", False):
                            ack = getattr(gap_rep, "acknowledgment", None)
                            if ack and ack not in seen_status:
                                yield StreamTurnEvent(event_type="status", delta=ack)

                        disp_res = getattr(job_res, "dispatch_result", None)
                        envelope = getattr(disp_res, "envelope", None)
                        if envelope and getattr(envelope, "summary", ""):
                            comp_text = f"[COMPLETED: {envelope.summary}]"
                            completion_summaries.append(comp_text)
                            yield StreamTurnEvent(event_type="delta", delta=f"\n\n{comp_text}")

                        yield StreamTurnEvent(event_type="job_dispatched", dispatched_job=job_res)
                    except Exception as exc:
                        yield StreamTurnEvent(
                            event_type="error", error_message=f"Job dispatch error: {exc}"
                        )

            # 2. Direct tool calls -> tool_dispatcher
            direct_calls = [c for c in terminal_tool_calls if c.name != "fulfill_request"]
            if direct_calls and self.tool_dispatcher:
                for call in direct_calls:
                    try:
                        params = json.loads(call.arguments) if call.arguments else {}
                    except Exception:
                        params = {}
                    try:
                        tool_res = await self.tool_dispatcher(call.name, params)
                        yield StreamTurnEvent(
                            event_type="tool_executed",
                            tool_result=tool_res,
                        )
                    except Exception as exc:
                        yield StreamTurnEvent(
                            event_type="error",
                            error_message=f"Tool execution error: {exc}",
                        )
            final_content = accumulated_text
            if completion_summaries:
                final_content += "\n\n" + "\n\n".join(completion_summaries)

            if accumulated_reasoning_parts and "<think>" not in final_content:
                reasoning_str = "".join(accumulated_reasoning_parts).strip()
                if reasoning_str:
                    final_content = f"<think>\n{reasoning_str}\n</think>\n\n{final_content}"

            assistant_turn = self.session_repo.append_turn(
                session_id=self.session_id,
                role="assistant",
                content=final_content,
                token_count=estimate_tokens(final_content),
            )

            yield StreamTurnEvent(
                event_type="completed",
                turn=assistant_turn,
            )
        except Exception as err:
            yield StreamTurnEvent(
                event_type="error",
                error_message=str(err),
            )
