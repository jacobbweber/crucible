"""Domain models for long-term memory and atomic fact storage."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class FactRecord(BaseModel):
    """Represents an atomic, searchable knowledge fact."""

    fact_id: str
    entity_key: str = Field(min_length=1)
    fact_text: str = Field(min_length=1)
    category: str = Field(default="general")
    source_turn_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class FactSearchResult(BaseModel):
    """Result of a lexical or semantic fact search query."""

    fact: FactRecord
    score: float = 0.0


class RecalledFactsPayload(BaseModel):
    """Schema representing recalled facts and token budget estimates."""

    rendered_block: str = ""
    recalled_count: int = 0
    token_estimate: int = 0
    matched_entity_keys: list[str] = Field(default_factory=list)
