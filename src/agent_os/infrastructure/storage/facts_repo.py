"""FactRepository implementation using SQLite with FTS5 lexical indexing."""

import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from agent_os.domain.memory import FactRecord, FactSearchResult
from agent_os.infrastructure.storage.facts_db import get_facts_connection, init_facts_db


class FactRepository:
    """Repository for managing atomic fact storage and FTS5 search retrieval."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_facts_db(self.db_path)

    def save_fact(
        self,
        entity_key: str,
        fact_text: str,
        category: str = "general",
        source_turn_id: str | None = None,
    ) -> FactRecord:
        """Persist a new fact record with automatic FTS5 synchronization."""
        fact_id = f"fact_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        now_str = now.isoformat()

        with get_facts_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO facts (
                    fact_id, entity_key, fact_text, category, source_turn_id,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (fact_id, entity_key, fact_text, category, source_turn_id, now_str, now_str),
            )

        return FactRecord(
            fact_id=fact_id,
            entity_key=entity_key,
            fact_text=fact_text,
            category=category,
            source_turn_id=source_turn_id,
            created_at=now,
            updated_at=now,
        )

    def get_fact(self, fact_id: str) -> FactRecord | None:
        """Retrieve a single fact by its ID or return None."""
        with get_facts_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT fact_id, entity_key, fact_text, category, source_turn_id,
                       created_at, updated_at
                FROM facts
                WHERE fact_id = ?;
                """,
                (fact_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return FactRecord(
            fact_id=row["fact_id"],
            entity_key=row["entity_key"],
            fact_text=row["fact_text"],
            category=row["category"],
            source_turn_id=row["source_turn_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def update_fact(
        self,
        fact_id: str,
        new_text: str,
        category: str | None = None,
    ) -> FactRecord:
        """Update fact text and optional category, setting updated_at to UTC now."""
        now = datetime.now(UTC)
        now_str = now.isoformat()

        with get_facts_connection(self.db_path) as conn:
            if category is not None:
                cursor = conn.execute(
                    """
                    UPDATE facts
                    SET fact_text = ?, category = ?, updated_at = ?
                    WHERE fact_id = ?;
                    """,
                    (new_text, category, now_str, fact_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE facts
                    SET fact_text = ?, updated_at = ?
                    WHERE fact_id = ?;
                    """,
                    (new_text, now_str, fact_id),
                )

            if cursor.rowcount == 0:
                raise ValueError(f"Fact not found: {fact_id}")

        fact = self.get_fact(fact_id)
        if fact is None:
            raise ValueError(f"Fact not found after update: {fact_id}")
        return fact

    def delete_fact(self, fact_id: str) -> bool:
        """Delete fact from SQLite, propagating deletion to FTS5 via trigger."""
        with get_facts_connection(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM facts WHERE fact_id = ?;",
                (fact_id,),
            )
            return cursor.rowcount > 0

    def list_by_entity(self, entity_key: str) -> list[FactRecord]:
        """Return all facts for an exact entity_key ordered by created_at."""
        with get_facts_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT fact_id, entity_key, fact_text, category, source_turn_id,
                       created_at, updated_at
                FROM facts
                WHERE entity_key = ?
                ORDER BY created_at ASC;
                """,
                (entity_key,),
            )
            rows = cursor.fetchall()

        return [
            FactRecord(
                fact_id=row["fact_id"],
                entity_key=row["entity_key"],
                fact_text=row["fact_text"],
                category=row["category"],
                source_turn_id=row["source_turn_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def search_facts(self, query: str, limit: int = 10) -> list[FactSearchResult]:
        """Execute BM25 lexical ranking query on facts_fts and return matched results."""
        clean_query = query.strip()
        if not clean_query:
            return []

        sql = """
        SELECT f.fact_id, f.entity_key, f.fact_text, f.category, f.source_turn_id,
               f.created_at, f.updated_at, -bm25(facts_fts) AS score
        FROM facts_fts
        JOIN facts f ON f.rowid = facts_fts.rowid
        WHERE facts_fts MATCH ?
        ORDER BY bm25(facts_fts) ASC
        LIMIT ?;
        """

        with get_facts_connection(self.db_path) as conn:
            try:
                rows = conn.execute(sql, (clean_query, limit)).fetchall()
            except sqlite3.OperationalError:
                words = [w for w in re.findall(r"\w+", clean_query) if w]
                if not words:
                    return []
                safe_query = " ".join(f'"{w}"' for w in words)
                rows = conn.execute(sql, (safe_query, limit)).fetchall()

        results: list[FactSearchResult] = []
        for row in rows:
            fact = FactRecord(
                fact_id=row["fact_id"],
                entity_key=row["entity_key"],
                fact_text=row["fact_text"],
                category=row["category"],
                source_turn_id=row["source_turn_id"],
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            raw_score = float(row["score"])
            score = raw_score if raw_score > 0 else abs(raw_score)
            results.append(FactSearchResult(fact=fact, score=score))

        return results
