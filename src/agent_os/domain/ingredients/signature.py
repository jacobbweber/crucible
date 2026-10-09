"""Capability signature representing an operation's verb, resource, scope, and effect."""

import re

from pydantic import BaseModel, Field, field_validator

from agent_os.domain.ingredients.vocabulary import Effect, Scope, Verb

_SIGNATURE_RE = re.compile(
    r"^(?P<verb>[a-z_]+):(?P<resource>[a-z_]+(?:\.[a-z_]+)*)@(?P<scope>[a-z_]+)\[(?P<effect>[a-z_]+)\]$"
)


class CapabilitySignature(BaseModel):
    """Declarative capability signature defining what an operation touches and alters."""

    verb: Verb
    resource: str = Field(min_length=1)
    scope: Scope
    effect: Effect

    @field_validator("resource")
    @classmethod
    def _validate_resource_pattern(cls, v: str) -> str:
        pattern = re.compile(r"^[a-z_]+(\.[a-z_]+)*$")
        if not pattern.match(v):
            raise ValueError(f"Resource '{v}' must match pattern '^[a-z_]+(\\.[a-z_]+)*$'.")
        return v

    def canonical_str(self) -> str:
        """Format signature as canonical string: verb:resource@scope[effect]."""
        return f"{self.verb.value}:{self.resource}@{self.scope.value}[{self.effect.value}]"

    def __str__(self) -> str:
        return self.canonical_str()

    def matches(self, other: "CapabilitySignature") -> bool:
        """Check if signatures match on verb, resource, and scope (ignoring effect)."""
        return (
            self.verb == other.verb
            and self.resource == other.resource
            and self.scope == other.scope
        )

    @classmethod
    def from_string(cls, sig_str: str) -> "CapabilitySignature":
        """Parse canonical signature string into a CapabilitySignature instance."""
        match = _SIGNATURE_RE.match(sig_str.strip())
        if not match:
            raise ValueError(
                f"Invalid capability signature format: '{sig_str}'. "
                "Expected format: verb:resource@scope[effect]"
            )
        return cls(
            verb=Verb(match.group("verb")),
            resource=match.group("resource"),
            scope=Scope(match.group("scope")),
            effect=Effect(match.group("effect")),
        )
