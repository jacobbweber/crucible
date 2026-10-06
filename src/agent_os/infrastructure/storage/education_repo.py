"""EducationRepository implementation for curriculum topics, SRS cards, and review logs."""

import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from agent_os.domain.education import EducationTopic, ReviewLog, SRSReviewCard
from agent_os.infrastructure.storage.education_db import (
    get_education_connection,
    init_education_db,
)


class EducationRepository:
    """Repository managing curriculum topics, SRS review cards, and execution logs."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_education_db(self.db_path)

    @staticmethod
    def _row_to_topic(row: sqlite3.Row) -> EducationTopic:
        return EducationTopic(
            topic_id=row["topic_id"],
            title=row["title"],
            category=row["category"],
            current_stage=row["current_stage"],
            mastery_score=float(row["mastery_score"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _row_to_card(row: sqlite3.Row) -> SRSReviewCard:
        last_reviewed = (
            datetime.fromisoformat(row["last_reviewed_at"])
            if row["last_reviewed_at"] is not None
            else None
        )
        return SRSReviewCard(
            card_id=row["card_id"],
            topic_id=row["topic_id"],
            prompt=row["prompt"],
            expected_answer=row["expected_answer"],
            repetitions=int(row["repetitions"]),
            interval_days=int(row["interval_days"]),
            ease_factor=float(row["ease_factor"]),
            due_date=datetime.fromisoformat(row["due_date"]),
            last_reviewed_at=last_reviewed,
        )

    def upsert_topic(self, topic: EducationTopic) -> EducationTopic:
        """Insert or update a curriculum topic record."""
        with get_education_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO topics (
                    topic_id, title, category, current_stage, mastery_score,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(topic_id) DO UPDATE SET
                    title = excluded.title,
                    category = excluded.category,
                    current_stage = excluded.current_stage,
                    mastery_score = excluded.mastery_score,
                    updated_at = excluded.updated_at;
                """,
                (
                    topic.topic_id,
                    topic.title,
                    topic.category,
                    topic.current_stage,
                    topic.mastery_score,
                    topic.created_at.isoformat(),
                    topic.updated_at.isoformat(),
                ),
            )
        return topic

    def get_topic(self, topic_id: str) -> EducationTopic | None:
        """Retrieve a curriculum topic by its unique ID."""
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT topic_id, title, category, current_stage, mastery_score,
                       created_at, updated_at
                FROM topics
                WHERE topic_id = ?;
                """,
                (topic_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_topic(row)

    def add_review_card(self, card: SRSReviewCard) -> SRSReviewCard:
        """Insert or replace an SRS review card."""
        last_reviewed_str = card.last_reviewed_at.isoformat() if card.last_reviewed_at else None
        with get_education_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_cards (
                    card_id, topic_id, prompt, expected_answer, repetitions,
                    interval_days, ease_factor, due_date, last_reviewed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(card_id) DO UPDATE SET
                    topic_id = excluded.topic_id,
                    prompt = excluded.prompt,
                    expected_answer = excluded.expected_answer,
                    repetitions = excluded.repetitions,
                    interval_days = excluded.interval_days,
                    ease_factor = excluded.ease_factor,
                    due_date = excluded.due_date,
                    last_reviewed_at = excluded.last_reviewed_at;
                """,
                (
                    card.card_id,
                    card.topic_id,
                    card.prompt,
                    card.expected_answer,
                    card.repetitions,
                    card.interval_days,
                    card.ease_factor,
                    card.due_date.isoformat(),
                    last_reviewed_str,
                ),
            )
        return card

    def get_card(self, card_id: str) -> SRSReviewCard | None:
        """Retrieve a review card by ID."""
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT card_id, topic_id, prompt, expected_answer, repetitions,
                       interval_days, ease_factor, due_date, last_reviewed_at
                FROM review_cards
                WHERE card_id = ?;
                """,
                (card_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_card(row)

    def get_due_cards(self, as_of: datetime, limit: int = 20) -> list[SRSReviewCard]:
        """Retrieve review cards due on or before as_of timestamp."""
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT card_id, topic_id, prompt, expected_answer, repetitions,
                       interval_days, ease_factor, due_date, last_reviewed_at
                FROM review_cards
                WHERE due_date <= ?
                ORDER BY due_date ASC
                LIMIT ?;
                """,
                (as_of.isoformat(), limit),
            )
            rows = cursor.fetchall()
        return [self._row_to_card(row) for row in rows]

    def record_review(
        self,
        card_id: str,
        grade: int,
        new_interval: int,
        new_repetitions: int,
        new_ease_factor: float,
        reviewed_at: datetime | str,
    ) -> ReviewLog:
        """Record review outcome, update card intervals and timestamps, and write audit log."""
        actual_reviewed_at = (
            datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
            if isinstance(reviewed_at, str)
            else reviewed_at
        )
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT interval_days FROM review_cards WHERE card_id = ?;",
                (card_id,),
            )
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Card not found: {card_id}")
            old_interval = int(row["interval_days"])

            new_due_date = actual_reviewed_at + timedelta(days=new_interval)
            conn.execute(
                """
                UPDATE review_cards
                SET repetitions = ?,
                    interval_days = ?,
                    ease_factor = ?,
                    last_reviewed_at = ?,
                    due_date = ?
                WHERE card_id = ?;
                """,
                (
                    new_repetitions,
                    new_interval,
                    new_ease_factor,
                    actual_reviewed_at.isoformat(),
                    new_due_date.isoformat(),
                    card_id,
                ),
            )

            log_id = f"log_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO review_logs (
                    log_id, card_id, grade, reviewed_at, old_interval, new_interval
                )
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    log_id,
                    card_id,
                    grade,
                    actual_reviewed_at.isoformat(),
                    old_interval,
                    new_interval,
                ),
            )

        return ReviewLog(
            log_id=log_id,
            card_id=card_id,
            grade=grade,
            reviewed_at=actual_reviewed_at,
            old_interval=old_interval,
            new_interval=new_interval,
        )

    def list_logs_for_card(self, card_id: str) -> list[ReviewLog]:
        """Retrieve all review logs for a card."""
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT log_id, card_id, grade, reviewed_at, old_interval, new_interval
                FROM review_logs
                WHERE card_id = ?
                ORDER BY reviewed_at DESC;
                """,
                (card_id,),
            )
            rows = cursor.fetchall()
        return [
            ReviewLog(
                log_id=r["log_id"],
                card_id=r["card_id"],
                grade=int(r["grade"]),
                reviewed_at=datetime.fromisoformat(r["reviewed_at"]),
                old_interval=int(r["old_interval"]),
                new_interval=int(r["new_interval"]),
            )
            for r in rows
        ]

    def get_topic_review_stats(self, topic_id: str) -> tuple[int, float]:
        """Calculate consecutive high grades (grade >= 4) and mastery score (0-100)."""
        with get_education_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT l.grade
                FROM review_logs l
                JOIN review_cards c ON l.card_id = c.card_id
                WHERE c.topic_id = ?
                ORDER BY l.reviewed_at DESC;
                """,
                (topic_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            return 0, 0.0

        grades = [int(r["grade"]) for r in rows]
        consecutive_high = 0
        for g in grades:
            if g >= 4:
                consecutive_high += 1
            else:
                break

        avg_grade = sum(grades) / len(grades)
        mastery_score = round((avg_grade / 5.0) * 100.0, 1)
        return consecutive_high, mastery_score

