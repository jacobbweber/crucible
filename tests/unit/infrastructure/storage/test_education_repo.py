"""Unit tests for EducationRepository topic, card, and review log operations."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_os.domain.education import EducationTopic, SRSReviewCard
from agent_os.infrastructure.storage.education_repo import EducationRepository


def test_upsert_topic_and_cards(tmp_path: Path) -> None:
    """Create topic with 2 review cards; verify query returns due cards."""
    db_file = tmp_path / "education.db"
    repo = EducationRepository(db_file)

    topic = EducationTopic(
        topic_id="raft_consensus",
        title="Raft Consensus Algorithm",
        category="distributed_systems",
        current_stage="stage_2_mental_models",
        mastery_score=25.0,
    )
    repo.upsert_topic(topic)

    retrieved_topic = repo.get_topic("raft_consensus")
    assert retrieved_topic is not None
    assert retrieved_topic.title == "Raft Consensus Algorithm"
    assert retrieved_topic.current_stage == "stage_2_mental_models"

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    card_due = SRSReviewCard(
        card_id="card_leader_election",
        topic_id="raft_consensus",
        prompt="How is a leader elected in Raft?",
        expected_answer="Candidate requests votes after randomized timeout.",
        due_date=now - timedelta(days=1),
    )
    card_future = SRSReviewCard(
        card_id="card_log_replication",
        topic_id="raft_consensus",
        prompt="How does log replication achieve safety?",
        expected_answer="Majority append entries acknowledgment before commit.",
        due_date=now + timedelta(days=3),
    )
    repo.add_review_card(card_due)
    repo.add_review_card(card_future)

    due_cards = repo.get_due_cards(as_of=now)
    assert len(due_cards) == 1
    assert due_cards[0].card_id == "card_leader_election"
    assert due_cards[0].topic_id == "raft_consensus"


def test_record_review_log(tmp_path: Path) -> None:
    """Record grade 4 review; verify card due date advances and log record is written."""
    db_file = tmp_path / "education.db"
    repo = EducationRepository(db_file)

    topic = EducationTopic(
        topic_id="paxos_consensus",
        title="Paxos Protocol",
        category="distributed_systems",
    )
    repo.upsert_topic(topic)

    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    card = SRSReviewCard(
        card_id="card_paxos_phase1",
        topic_id="paxos_consensus",
        prompt="What happens in Paxos Phase 1b?",
        expected_answer="Acceptors reply with promise and highest-numbered accepted proposal.",
        repetitions=0,
        interval_days=1,
        ease_factor=2.5,
        due_date=now,
    )
    repo.add_review_card(card)

    log = repo.record_review(
        card_id="card_paxos_phase1",
        grade=4,
        new_interval=6,
        new_repetitions=1,
        new_ease_factor=2.5,
        reviewed_at=now,
    )

    assert log.card_id == "card_paxos_phase1"
    assert log.grade == 4
    assert log.old_interval == 1
    assert log.new_interval == 6
    assert log.reviewed_at == now

    updated_card = repo.get_card("card_paxos_phase1")
    assert updated_card is not None
    assert updated_card.repetitions == 1
    assert updated_card.interval_days == 6
    assert updated_card.ease_factor == 2.5
    assert updated_card.last_reviewed_at == now
    assert updated_card.due_date == now + timedelta(days=6)

    logs = repo.list_logs_for_card("card_paxos_phase1")
    assert len(logs) == 1
    assert logs[0].log_id == log.log_id
