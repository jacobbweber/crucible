"""RecipeRepository implementation using SQLite with FTS5 lexical indexing."""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_os.domain.recipe import RecipeMatch, RecipeMetadata, RecipeRecord
from agent_os.infrastructure.storage.recipe_db import get_recipe_connection, init_recipe_db
from agent_os.infrastructure.storage.text_utils import STOP_WORDS


class RecipeRepository:
    """Repository for managing execution recipes and FTS5 intent matching."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path.resolve()
        init_recipe_db(self.db_path)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RecipeRecord:
        raw_tags: Any = json.loads(row["tags_json"])
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []

        raw_tools: Any = json.loads(row["required_tools_json"])
        required_tools = [str(t) for t in raw_tools] if isinstance(raw_tools, list) else []

        metadata = RecipeMetadata(
            recipe_id=row["recipe_id"],
            name=row["name"],
            description=row["description"],
            execution_engine=row["execution_engine"],
            target_model_tier=row["target_model_tier"],
            tags=tags,
            required_tools=required_tools,
            timeout_seconds=int(row["timeout_seconds"]),
        )
        return RecipeRecord(
            metadata=metadata,
            markdown_path=row["markdown_path"],
            body=row["body"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def upsert_recipe(self, record: RecipeRecord) -> RecipeRecord:
        """Insert or replace recipe record in recipes.db."""
        tags_json = json.dumps(record.metadata.tags)
        tools_json = json.dumps(record.metadata.required_tools)
        created_at_str = record.created_at.isoformat()
        updated_at_str = record.updated_at.isoformat()

        with get_recipe_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO recipes (
                    recipe_id, name, description, execution_engine, target_model_tier,
                    tags_json, required_tools_json, timeout_seconds, markdown_path, body,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(recipe_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    execution_engine = excluded.execution_engine,
                    target_model_tier = excluded.target_model_tier,
                    tags_json = excluded.tags_json,
                    required_tools_json = excluded.required_tools_json,
                    timeout_seconds = excluded.timeout_seconds,
                    markdown_path = excluded.markdown_path,
                    body = excluded.body,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at;
                """,
                (
                    record.metadata.recipe_id,
                    record.metadata.name,
                    record.metadata.description,
                    record.metadata.execution_engine,
                    record.metadata.target_model_tier,
                    tags_json,
                    tools_json,
                    record.metadata.timeout_seconds,
                    record.markdown_path,
                    record.body,
                    created_at_str,
                    updated_at_str,
                ),
            )
        return record

    def get_recipe(self, recipe_id: str) -> RecipeRecord | None:
        """Retrieve a single recipe by its primary key or return None."""
        with get_recipe_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT recipe_id, name, description, execution_engine, target_model_tier,
                       tags_json, required_tools_json, timeout_seconds, markdown_path, body,
                       created_at, updated_at
                FROM recipes
                WHERE recipe_id = ?;
                """,
                (recipe_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None
        return self._row_to_record(row)

    def list_recipes(self) -> list[RecipeRecord]:
        """Retrieve all stored recipe records ordered by name."""
        with get_recipe_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT recipe_id, name, description, execution_engine, target_model_tier,
                       tags_json, required_tools_json, timeout_seconds, markdown_path, body,
                       created_at, updated_at
                FROM recipes
                ORDER BY name ASC;
                """
            )
            rows = cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    def delete_recipe(self, recipe_id: str) -> bool:
        """Delete recipe from SQLite, propagating deletion to FTS5 via trigger."""
        with get_recipe_connection(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM recipes WHERE recipe_id = ?;",
                (recipe_id,),
            )
            return cursor.rowcount > 0

    def match_intent(self, task: str, limit: int = 3) -> list[RecipeMatch]:
        """Query recipes_fts using BM25 ranking matching against task."""
        clean_task = task.strip()
        if not clean_task:
            return []

        words = [w.lower() for w in re.findall(r"\w+", clean_task) if w]
        meaningful_words = [w for w in words if len(w) > 1 and w not in STOP_WORDS]
        if not meaningful_words:
            return []

        fts_query = " OR ".join(f'"{w}"' for w in meaningful_words)
        sql = """
        SELECT r.recipe_id, r.name, r.description, r.execution_engine, r.target_model_tier,
               r.tags_json, r.required_tools_json, r.timeout_seconds, r.markdown_path, r.body,
               r.created_at, r.updated_at, -bm25(recipes_fts) AS score
        FROM recipes_fts
        JOIN recipes r ON r.rowid = recipes_fts.rowid
        WHERE recipes_fts MATCH ?
        ORDER BY bm25(recipes_fts) ASC
        LIMIT ?;
        """

        with get_recipe_connection(self.db_path) as conn:
            try:
                rows = conn.execute(sql, (fts_query, limit)).fetchall()
            except sqlite3.OperationalError:
                return []

        results: list[RecipeMatch] = []
        for row in rows:
            record = self._row_to_record(row)
            raw_score = float(row["score"])
            # Scale SQLite FTS5 clamped BM25 magnitude (~1e-6) to standard unit scale
            score = (raw_score if raw_score > 0 else abs(raw_score)) * 1e6
            results.append(RecipeMatch(recipe=record, score=score))

        return results
