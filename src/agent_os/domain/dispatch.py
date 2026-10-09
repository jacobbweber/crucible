"""Domain models for zero-catalog dispatch decisions and results."""

from typing import Literal

from pydantic import BaseModel, Field

from agent_os.domain.ipc import SubJobReturnEnvelope


class DispatchDecision(BaseModel):
    """Routing and assembly decision computed by the ZeroCatalogDispatcher."""

    task: str
    stage: Literal["matched_recipe", "assembled_ephemeral"]
    matched_recipe_id: str | None = None
    confidence_score: float = 0.0
    ephemeral_tools: list[str] = Field(default_factory=list)


class DispatchResult(BaseModel):
    """Aggregate result holding the dispatch decision and isolated worker envelope."""

    decision: DispatchDecision
    envelope: SubJobReturnEnvelope

    @property
    def success(self) -> bool:
        """True if the worker execution completed successfully."""
        return self.envelope.status == "completed"

    @property
    def error(self) -> str | None:
        """Error string if the worker execution did not complete."""
        return None if self.success else self.envelope.summary
