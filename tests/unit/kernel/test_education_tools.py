"""Unit tests for EducationToolSuite tool definitions and execution handlers."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_os.domain.education import EducationTopic, SRSReviewCard
from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.storage.education_repo import EducationRepository
from agent_os.kernel.education_tools import EducationToolSuite
from agent_os.kernel.srs_engine import SRSEngine


def test_education_tools_definitions(tmp_path: Path) -> None:
    """Verify definitions match ActionTier.STATE_CHANGE."""
    repo = EducationRepository(tmp_path / "education.db")
    srs = SRSEngine()
    suite = EducationToolSuite(education_repo=repo, srs_engine=srs)

    defs = suite.get_definitions()
    names = {d.name for d in defs}
    assert {"education_record_grade", "education_advance_stage"}.issubset(names)

    for tool_def in defs:
        assert tool_def.action_tier == ActionTier.STATE_CHANGE


def test_education_record_grade_execution(tmp_path: Path) -> None:
    """Call tool with grade 5; verify card due date updated and review log persisted in SQLite."""
    repo = EducationRepository(tmp_path / "education.db")
    srs = SRSEngine()
    suite = EducationToolSuite(education_repo=repo, srs_engine=srs)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    topic = EducationTopic(
        topic_id="distributed_systems",
        title="Distributed Systems",
        category="core",
    )
    repo.upsert_topic(topic)

    card = SRSReviewCard(
        card_id="card_cap_theorem",
        topic_id="distributed_systems",
        prompt="State the CAP theorem tradeoffs.",
        expected_answer="Consistency, Availability, Partition tolerance - pick two.",
        repetitions=0,
        interval_days=1,
        ease_factor=2.5,
        due_date=now,
    )
    repo.add_review_card(card)

    result = suite.education_record_grade(card_id="card_cap_theorem", grade=5, reviewed_at=now)
    assert result.success is True
    assert "Recorded grade 5" in result.output

    updated_card = repo.get_card("card_cap_theorem")
    assert updated_card is not None
    assert updated_card.repetitions == 1
    assert updated_card.interval_days == 1
    assert updated_card.ease_factor == 2.6
    assert updated_card.last_reviewed_at == now
    assert updated_card.due_date == now + timedelta(days=1)

    logs = repo.list_logs_for_card("card_cap_theorem")
    assert len(logs) == 1
    assert logs[0].grade == 5
    assert logs[0].new_interval == 1


def test_education_advance_stage_execution(tmp_path: Path) -> None:
    """Call tool to advance stage; verify topic record in SQLite reflects updated stage."""
    repo = EducationRepository(tmp_path / "education.db")
    srs = SRSEngine()
    suite = EducationToolSuite(education_repo=repo, srs_engine=srs)

    topic = EducationTopic(
        topic_id="k8s_internals",
        title="Kubernetes Internals",
        category="infrastructure",
        current_stage="stage_1_primer",
    )
    repo.upsert_topic(topic)

    result = suite.education_advance_stage(
        topic_id="k8s_internals",
        target_stage="stage_2_mental_models",
        rationale="Demonstrated strong grasp of etcd and control plane invariants.",
    )
    assert result.success is True
    assert "Advanced Kubernetes Internals to stage_2_mental_models" in result.output

    updated_topic = repo.get_topic("k8s_internals")
    assert updated_topic is not None
    assert updated_topic.current_stage == "stage_2_mental_models"
