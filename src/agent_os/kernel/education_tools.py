"""Education assessment tools and tool suite definitions."""

from datetime import UTC, datetime

from agent_os.domain.education import PedagogicalStage
from agent_os.domain.policy import ActionTier
from agent_os.domain.tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolParameterSchema,
)
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.kernel.pedagogical import STAGE_PROGRESSION, PedagogicalOrchestrator
from agent_os.kernel.srs_engine import SRSEngine


class EducationToolSuite:
    """Tool suite providing agent access to educational SRS tracking and stage transitions."""

    def __init__(
        self,
        education_repo: EducationRepository,
        srs_engine: SRSEngine,
    ) -> None:
        self.repo = education_repo
        self.education_repo = education_repo
        self.srs = srs_engine
        self.srs_engine = srs_engine

    def get_definitions(self) -> list[ToolDefinition]:
        """Return tool definitions for education assessment and stage management."""
        return [
            ToolDefinition(
                name="education_record_grade",
                description="Record SM-2 review score (0-5) for an SRS card and advance intervals.",
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    ToolParameterSchema(
                        name="card_id",
                        type_name="string",
                        description="Unique identifier of the SRS review card.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="grade",
                        type_name="integer",
                        description="SuperMemo SM-2 quality grade from 0 to 5.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="reviewed_at",
                        type_name="string",
                        description="Optional ISO timestamp representing the review time.",
                        required=False,
                    ),
                ],
            ),
            ToolDefinition(
                name="education_advance_stage",
                description=(
                    "Advance curriculum topic to next pedagogical stage upon meeting criteria."
                ),
                action_tier=ActionTier.STATE_CHANGE,
                parameters=[
                    ToolParameterSchema(
                        name="topic_id",
                        type_name="string",
                        description="Unique identifier of the curriculum topic.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="target_stage",
                        type_name="string",
                        description="Target pedagogical stage to transition into.",
                        required=True,
                    ),
                    ToolParameterSchema(
                        name="rationale",
                        type_name="string",
                        description="Rationale explaining mastery evidence for stage transition.",
                        required=True,
                    ),
                ],
            ),
        ]

    def education_record_grade(
        self,
        card_id: str,
        grade: int,
        reviewed_at: datetime | str | None = None,
    ) -> ToolExecutionResult:
        """Validate grade, calculate SM-2 intervals, update card, and log review event (M3)."""
        if grade < 0 or grade > 5:
            return ToolExecutionResult(
                tool_name="education_record_grade",
                success=False,
                output="",
                error=f"Grade must be between 0 and 5, got {grade}",
            )

        review_time: datetime
        if reviewed_at is None:
            review_time = datetime.now(UTC)
        elif isinstance(reviewed_at, datetime):
            review_time = reviewed_at
        elif isinstance(reviewed_at, str):
            try:
                review_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            except Exception as e:
                return ToolExecutionResult(
                    tool_name="education_record_grade",
                    success=False,
                    output="",
                    error=f"Invalid ISO timestamp for reviewed_at '{reviewed_at}': {e}",
                )
        else:
            return ToolExecutionResult(
                tool_name="education_record_grade",
                success=False,
                output="",
                error=f"Unsupported type for reviewed_at: {type(reviewed_at).__name__}",
            )

        card = self.repo.get_card(card_id)
        if card is None:
            return ToolExecutionResult(
                tool_name="education_record_grade",
                success=False,
                output="",
                error=f"Card not found: {card_id}",
            )

        new_reps, new_interval, new_ease = self.srs.calculate_sm2(
            grade=grade,
            repetitions=card.repetitions,
            interval_days=card.interval_days,
            ease_factor=card.ease_factor,
        )

        self.repo.record_review(
            card_id=card_id,
            grade=grade,
            new_interval=new_interval,
            new_repetitions=new_reps,
            new_ease_factor=new_ease,
            reviewed_at=review_time,
        )

        # Update topic mastery score and evaluate pedagogical advancement readiness (M3)
        extra = ""
        topic = self.repo.get_topic(card.topic_id)
        if topic is not None:
            consecutive_high, mastery = self.repo.get_topic_review_stats(topic.topic_id)
            topic.mastery_score = mastery
            topic.updated_at = datetime.now(UTC)
            self.repo.upsert_topic(topic)

            next_stage, advanced = PedagogicalOrchestrator.evaluate_stage_transition(
                topic.current_stage, consecutive_high, mastery
            )
            if advanced:
                extra = (
                    f" Topic '{topic.title}' is eligible to advance to {next_stage} "
                    f"(mastery: {mastery}%, consecutive high: {consecutive_high})."
                )
            else:
                extra = f" Topic '{topic.title}' mastery: {mastery}%."

        return ToolExecutionResult(
            tool_name="education_record_grade",
            success=True,
            output=f"Recorded grade {grade}. New interval: {new_interval} days.{extra}",
        )

    def education_advance_stage(
        self,
        topic_id: str,
        target_stage: PedagogicalStage,
        rationale: str,
    ) -> ToolExecutionResult:
        """Advance topic to target pedagogical stage with validation and rubric guidance."""
        topic = self.repo.get_topic(topic_id)
        if topic is None:
            return ToolExecutionResult(
                tool_name="education_advance_stage",
                success=False,
                output="",
                error=f"Topic {topic_id} not found",
            )

        if target_stage not in STAGE_PROGRESSION:
            return ToolExecutionResult(
                tool_name="education_advance_stage",
                success=False,
                output="",
                error=f"Invalid target stage '{target_stage}'. Valid stages: {STAGE_PROGRESSION}",
            )

        if topic.current_stage == target_stage:
            return ToolExecutionResult(
                tool_name="education_advance_stage",
                success=False,
                output="",
                error=f"Topic '{topic.title}' is already at {target_stage}",
            )

        topic.current_stage = target_stage
        topic.updated_at = datetime.now(UTC)
        self.repo.upsert_topic(topic)
        rubric = PedagogicalOrchestrator.get_stage_rubric(target_stage)

        return ToolExecutionResult(
            tool_name="education_advance_stage",
            success=True,
            output=(
                f"Advanced {topic.title} to {target_stage}. Rubric: {rubric} Rationale: {rationale}"
            ),
        )
