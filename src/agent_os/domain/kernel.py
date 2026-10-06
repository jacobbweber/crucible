"""Domain models for master orchestration kernel configuration, turn requests, and responses."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from agent_os.domain.continuum import StreamTurnEvent
from agent_os.domain.pipeline import PipelineExecutionResult
from agent_os.domain.signaling import AmbientNudge


class KernelConfig(BaseModel):
    """Runtime configuration parameters for the AgentOS master kernel."""

    storage_root: str = ""
    companion_name: str = "Companion"
    max_concurrency: int = 1
    approval_mode: str = "balanced"
    context_window: int = 8192
    reserve_output_tokens: int = 1024


class UserTurnRequest(BaseModel):
    """User turn request payload for interactive companion dialogue."""

    session_id: str
    user_input: str


class TurnResponse(BaseModel):
    """Aggregated response for a single conversational turn."""

    session_id: str
    response_text: str
    stream_events: list[StreamTurnEvent] = Field(default_factory=list)
    recalled_facts_count: int = 0
    dispatched_subjobs: list[PipelineExecutionResult] = Field(default_factory=list)
    ambient_nudges: list[AmbientNudge] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
