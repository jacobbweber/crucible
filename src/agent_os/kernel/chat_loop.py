"""Interactive companion session orchestrator managing turns and context sliding window."""

from collections.abc import AsyncIterator

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import ChatSessionState, StreamTurnEvent
from agent_os.domain.gateway import ChatMessage, CompletionRequest, estimate_tokens
from agent_os.domain.session import TurnRecord
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.storage.session_repo import SessionRepository
from agent_os.kernel.prompt_assembler import PromptAssembler


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
        self.assembler = PromptAssembler(config)

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
            history_messages = self._select_history_within_budget(
                user_turn.turn_id, history_budget
            )

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
            )

            accumulated_text_parts: list[str] = []
            async for chunk in self.model_adapter.complete(request):
                if chunk.reasoning:
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

            accumulated_text = "".join(accumulated_text_parts)
            assistant_turn = self.session_repo.append_turn(
                session_id=self.session_id,
                role="assistant",
                content=accumulated_text,
                token_count=estimate_tokens(accumulated_text),
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
