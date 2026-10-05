"""Interactive companion session orchestrator managing turns and context sliding window."""

from collections.abc import AsyncIterator

from agent_os.domain.companion import CompanionConfig
from agent_os.domain.continuum import ChatSessionState, StreamTurnEvent
from agent_os.domain.gateway import ChatMessage, CompletionRequest
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
    ) -> None:
        self.session_id = session_id
        self.session_repo = session_repo
        self.repo = session_repo
        self.model_adapter = model_adapter
        self.adapter = model_adapter
        self.config = config
        self.sliding_window_size = sliding_window_size
        self.target_model = target_model
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

    async def execute_turn(
        self,
        user_input: str,
        recalled_facts_block: str = "",
        background_completions_block: str = "",
    ) -> AsyncIterator[StreamTurnEvent]:
        """Execute a single conversational turn with streaming inference and persistence."""
        try:
            user_turn = self.session_repo.append_turn(
                session_id=self.session_id,
                role="user",
                content=user_input,
                token_count=len(user_input) // 4,
            )

            assembled = self.assembler.assemble_system_prompt(
                recalled_facts_block=recalled_facts_block,
                background_completions_block=background_completions_block,
            )

            recent_turns = self.session_repo.get_recent_turns(
                self.session_id, limit=self.sliding_window_size + 1
            )
            history = [t for t in recent_turns if t.turn_id != user_turn.turn_id][
                -self.sliding_window_size :
            ]

            messages: list[ChatMessage] = [
                ChatMessage(role="system", content=assembled.rendered_prompt)
            ]
            for t in history:
                messages.append(ChatMessage(role=t.role, content=t.content))
            messages.append(ChatMessage(role="user", content=user_input))

            request = CompletionRequest(
                model=self.target_model,
                messages=messages,
                stream=True,
            )

            accumulated_text_parts: list[str] = []
            async for chunk in self.model_adapter.complete(request):
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
                token_count=len(accumulated_text) // 4,
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
