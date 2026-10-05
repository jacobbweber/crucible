"""Domain models for recipe metadata, full recipe records, and intent matching results."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class RecipeMetadata(BaseModel):
    """Declarative metadata defining an execution recipe."""

    recipe_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    execution_engine: Literal["direct", "react", "plan_execute_verify", "stategraph"] = "react"
    target_model_tier: Literal["fast", "reasoning", "coding"] = "reasoning"
    tags: list[str] = Field(min_length=1)
    required_tools: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=10)


class RecipeRecord(BaseModel):
    """Represents a complete recipe stored with metadata and markdown body."""

    metadata: RecipeMetadata
    markdown_path: str
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RecipeMatch(BaseModel):
    """Result of an intent-matching query against stored recipes."""

    recipe: RecipeRecord
    score: float = 0.0
