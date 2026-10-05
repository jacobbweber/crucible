"""Domain models for companion configuration, personality tone, and assembled prompts."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TonePreset(StrEnum):
    """Tone presets for system prompt styling."""

    CONCISE = "concise"
    FRIENDLY = "friendly"
    ANALYTICAL = "analytical"
    EMPTY = "empty"


class HumanProfile(BaseModel):
    """User profile metadata and preferences scoped for companion prompt assembly."""

    summary: str = Field(default="", max_length=2500)
    preferences: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CompanionConfig(BaseModel):
    """Configuration defining companion identity, tone, and user context."""

    name: str = Field(min_length=1, max_length=50, default="Companion")
    internal_slug: str = "companion_core"
    tone: TonePreset = TonePreset.EMPTY
    human_profile: HumanProfile = Field(default_factory=HumanProfile)


class AssembledSystemPrompt(BaseModel):
    """Rendered system prompt bundle with heuristic token estimation and context flags."""

    rendered_prompt: str
    token_estimate: int
    has_human_profile: bool
