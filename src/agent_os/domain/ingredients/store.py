"""Domain repository interface for managing versioned ingredients."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientKind,
    IngredientStatus,
)
from agent_os.domain.ingredients.vocabulary import Scope, Verb


@runtime_checkable
class IngredientRepository(Protocol):
    """Port interface for persisting and retrieving versioned ingredients."""

    def save(self, ingredient: IngredientEnvelope) -> IngredientEnvelope:
        """Validate and persist an ingredient record, returning the saved instance."""
        ...

    def get(self, ingredient_id: str, version: int | None = None) -> IngredientEnvelope | None:
        """Fetch an ingredient by ID. If version is None, return highest active or candidate."""
        ...

    def list(
        self,
        kind: IngredientKind | None = None,
        status: IngredientStatus | None = None,
    ) -> list[IngredientEnvelope]:
        """List ingredients matching optional kind and status filters."""
        ...

    def find_by_signature(
        self,
        verb: Verb,
        resource: str,
        scope: Scope,
    ) -> list[IngredientEnvelope]:
        """Lookup ingredients declaring a matching capability signature."""
        ...
