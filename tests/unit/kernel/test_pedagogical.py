"""Unit tests for PedagogicalOrchestrator rubrics and 6-stage transition evaluation."""

from agent_os.kernel.pedagogical import STAGE_PROGRESSION, PedagogicalOrchestrator


def test_pedagogical_rubric_resolution() -> None:
    """Verify all 6 stages produce distinct rubrics."""
    rubrics: set[str] = set()
    for stage in STAGE_PROGRESSION:
        rubric = PedagogicalOrchestrator.get_stage_rubric(stage)
        assert rubric is not None
        assert len(rubric) > 10
        rubrics.add(rubric)

    assert len(rubrics) == len(STAGE_PROGRESSION) == 6


def test_stage_transition_advance_on_mastery() -> None:
    """Pass consecutive_high_grades=3 and mastery_score=85.0; verify transition to stage_2."""
    next_stage, advanced = PedagogicalOrchestrator.evaluate_stage_transition(
        current_stage="stage_1_primer",
        consecutive_high_grades=3,
        mastery_score=85.0,
    )
    assert advanced is True
    assert next_stage == "stage_2_mental_models"


def test_stage_transition_hold_when_unmet() -> None:
    """Pass low score or insufficient consecutive high grades; verify stage does not advance."""
    # Insufficient mastery score
    stage, advanced = PedagogicalOrchestrator.evaluate_stage_transition(
        current_stage="stage_2_mental_models",
        consecutive_high_grades=3,
        mastery_score=75.0,
    )
    assert advanced is False
    assert stage == "stage_2_mental_models"

    # Insufficient consecutive high grades
    stage, advanced = PedagogicalOrchestrator.evaluate_stage_transition(
        current_stage="stage_2_mental_models",
        consecutive_high_grades=2,
        mastery_score=90.0,
    )
    assert advanced is False
    assert stage == "stage_2_mental_models"


def test_stage_transition_terminal_stage() -> None:
    """Verify stage_6_synthesis does not advance beyond terminal stage 6."""
    stage, advanced = PedagogicalOrchestrator.evaluate_stage_transition(
        current_stage="stage_6_synthesis",
        consecutive_high_grades=5,
        mastery_score=98.0,
    )
    assert advanced is False
    assert stage == "stage_6_synthesis"
