"""Ingredient metadata envelope, lifecycle status, provenance, and hashing."""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class IngredientKind(StrEnum):
    """The polymorphic ingredient types supporting recipe composition."""

    TOOL = "tool"
    CONTEXT_SOURCE = "context_source"
    MODEL_PROFILE = "model_profile"
    RUNBOOK = "runbook"
    RECIPE = "recipe"


class IngredientStatus(StrEnum):
    """Lifecycle state of an ingredient within the catalog."""

    DRAFT = "draft"
    CANDIDATE = "candidate"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"

    def is_usable_in_recipe(self) -> bool:
        """Only candidate and active ingredients can be referenced by recipes."""
        return self in (IngredientStatus.CANDIDATE, IngredientStatus.ACTIVE)


class Provenance(BaseModel):
    """Origin, authorship, and lifecycle timestamps for an ingredient."""

    author: str = Field(default="system")
    source_session_id: str | None = None
    source_journey_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def canonical_json_bytes(data: Any) -> bytes:
    """Serialize data to deterministic, canonical JSON bytes for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def compute_sha256(data: Any) -> str:
    """Compute sha256 hex digest over canonical JSON bytes."""
    return hashlib.sha256(canonical_json_bytes(data)).hexdigest()


class IngredientEnvelope(BaseModel):
    """Base envelope shared by all contract-first ingredient models."""

    id: str = Field(pattern=r"^[a-z0-9_-]+$", min_length=1)
    version: int = Field(default=1, ge=1)
    kind: IngredientKind
    status: IngredientStatus = IngredientStatus.CANDIDATE
    provenance: Provenance = Field(default_factory=Provenance)
    description: str = Field(min_length=1)
    content_hash: str = Field(default="")

    def pinned_ref(self) -> str:
        """Format pinned reference: id@version."""
        return f"{self.id}@{self.version}"

    @classmethod
    def parse_pinned_ref(cls, ref: str) -> tuple[str, int]:
        """Parse pinned reference id@version into (id, version)."""
        parts = ref.split("@")
        if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
            raise ValueError(f"Invalid pinned reference '{ref}'. Expected format: name@version")
        return parts[0], int(parts[1])
