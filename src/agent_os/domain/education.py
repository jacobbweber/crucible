"""Domain models for pedagogical curriculum, spaced repetition review cards, and logs."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

PedagogicalStage = Literal[
    "stage_1_primer",
    "stage_2_mental_models",
    "stage_3_scenario_probes",
    "stage_4_code_analysis",
    "stage_5_troubleshooting",
    "stage_6_synthesis",
]


class EducationTopic(BaseModel):
    """Curriculum topic representing a structured learning domain and current mastery."""

    topic_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    current_stage: PedagogicalStage = "stage_1_primer"
    mastery_score: float = Field(default=0.0, ge=0.0, le=100.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SRSReviewCard(BaseModel):
    """Spaced Repetition System review flashcard tracked by the SM-2 algorithm."""

    card_id: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    repetitions: int = Field(default=0, ge=0)
    interval_days: int = Field(default=1, ge=1)
    ease_factor: float = Field(default=2.5, ge=1.3)
    due_date: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_reviewed_at: datetime | None = None


class ReviewLog(BaseModel):
    """Audit log recording an individual card review event and interval transitions."""

    log_id: str = Field(
        default_factory=lambda: f"log_{uuid.uuid4().hex[:12]}",
        min_length=1,
    )
    card_id: str = Field(min_length=1)
    grade: int = Field(ge=0, le=5)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    old_interval: int
    new_interval: int


class EvaluationResult(BaseModel):
    """Result of assessing a learner's response against pedagogical rubrics."""

    grade: int = Field(ge=0, le=5)
    feedback: str = Field(min_length=1)
    passed: bool
    suggested_stage: PedagogicalStage | None = None


class StageTransition(BaseModel):
    """Record of progression evaluation between pedagogical stages."""

    topic_id: str
    previous_stage: PedagogicalStage
    new_stage: PedagogicalStage
    advanced: bool
    reason: str
