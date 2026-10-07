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
    assert "Rubric:" in result.output

    updated_topic = repo.get_topic("k8s_internals")
    assert updated_topic is not None
    assert updated_topic.current_stage == "stage_2_mental_models"


def test_education_record_grade_string_datetime_parsing(tmp_path: Path) -> None:
    """Verify ISO string reviewed_at formats (with Z and offset) parse correctly (M3)."""
    repo = EducationRepository(tmp_path / "education.db")
    suite = EducationToolSuite(education_repo=repo, srs_engine=SRSEngine())

    topic = EducationTopic(
        topic_id="raft_consensus",
        title="Raft Consensus",
        category="distributed",
    )
    repo.upsert_topic(topic)

    card = SRSReviewCard(
        card_id="card_raft_1",
        topic_id="raft_consensus",
        prompt="What is term in Raft?",
        expected_answer="Logical clock interval",
        repetitions=0,
        interval_days=1,
        ease_factor=2.5,
    )
    repo.add_review_card(card)

    # Test ISO string with Z
    res = suite.education_record_grade(
        card_id="card_raft_1",
        grade=4,
        reviewed_at="2026-10-06T12:00:00Z",  # type: ignore[arg-type]
    )
    assert res.success is True
    assert "Recorded grade 4" in res.output

    # Test invalid string timestamp
    res_err = suite.education_record_grade(
        card_id="card_raft_1",
        grade=4,
        reviewed_at="invalid-date-string",  # type: ignore[arg-type]
    )
    assert res_err.success is False
    assert "Invalid ISO timestamp" in (res_err.error or "")


def test_education_mastery_and_advancement_eligibility(tmp_path: Path) -> None:
    """3 consecutive grades >= 4 and mastery >= 80% marks topic as eligible to advance (M3)."""
    repo = EducationRepository(tmp_path / "education.db")
    suite = EducationToolSuite(education_repo=repo, srs_engine=SRSEngine())

    topic = EducationTopic(
        topic_id="linux_epoll",
        title="Linux epoll",
        category="kernel",
        current_stage="stage_1_primer",
    )
    repo.upsert_topic(topic)

    for i in range(3):
        card = SRSReviewCard(
            card_id=f"card_epoll_{i}",
            topic_id="linux_epoll",
            prompt=f"Prompt {i}",
            expected_answer=f"Answer {i}",
        )
        repo.add_review_card(card)

    # Record 3 consecutive grades of 5
    suite.education_record_grade(card_id="card_epoll_0", grade=5)
    suite.education_record_grade(card_id="card_epoll_1", grade=5)
    res3 = suite.education_record_grade(card_id="card_epoll_2", grade=5)

    assert res3.success is True
    assert "eligible to advance to stage_2_mental_models" in res3.output

    updated_topic = repo.get_topic("linux_epoll")
    assert updated_topic is not None
    assert updated_topic.mastery_score == 100.0


def test_education_advance_stage_validation(tmp_path: Path) -> None:
    """Advancing with an invalid stage or same stage returns an error."""
    repo = EducationRepository(tmp_path / "education.db")
    suite = EducationToolSuite(education_repo=repo, srs_engine=SRSEngine())

    topic = EducationTopic(
        topic_id="rust_borrowing",
        title="Rust Borrow Checker",
        category="language",
        current_stage="stage_1_primer",
    )
    repo.upsert_topic(topic)

    # Invalid stage
    err_res = suite.education_advance_stage(
        topic_id="rust_borrowing",
        target_stage="invalid_stage_xyz",  # type: ignore[arg-type]
        rationale="test",
    )
    assert err_res.success is False
    assert "Invalid target stage" in (err_res.error or "")

    # Same stage
    same_res = suite.education_advance_stage(
        topic_id="rust_borrowing",
        target_stage="stage_1_primer",
        rationale="test",
    )
    assert same_res.success is False
    assert "already at stage_1_primer" in (same_res.error or "")
