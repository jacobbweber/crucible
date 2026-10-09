"""Task intent structure captured from companion turns for recipe resolution."""

from typing import Any

from pydantic import BaseModel, Field

from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.vocabulary import Effect, Scope, Verb


class TaskIntent(BaseModel):
    """Structured intent representation produced when the companion fulfills a user request."""

    verb: Verb
    resource: str = Field(min_length=1)
    scope: Scope
    parameters: dict[str, Any] = Field(default_factory=dict)
    desired_output: str = Field(default="")
    normalized_utterance: str = Field(min_length=1)

    def to_capability_signature(self, effect: Effect = Effect.READ_ONLY) -> CapabilitySignature:
        """Derive a CapabilitySignature from the extracted intent and estimated/default effect."""
        return CapabilitySignature(
            verb=self.verb,
            resource=self.resource,
            scope=self.scope,
            effect=effect,
        )
