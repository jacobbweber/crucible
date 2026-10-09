"""Domain contracts and models for in-process embedding providers and semantic matches."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SemanticMatch(BaseModel):
    """Result of a semantic vector similarity search against candidate ingredients."""

    ingredient_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    score: float = Field(ge=-1.0, le=1.0)


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Port interface for producing dense vector embeddings."""

    @property
    def model_id(self) -> str:
        """Identifier of the active embedding model."""
        ...

    @property
    def dimension(self) -> int:
        """Output embedding vector dimensionality."""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute normalized vector embeddings for a list of document texts."""
        ...

    def embed_query(self, query: str) -> list[float]:
        """Compute a normalized vector embedding for a single search query."""
        ...
