"""Dense vector index for semantic capability and recipe retrieval in ingredients.db."""

import struct
from pathlib import Path

from agent_os.domain.ingredients.contracts import RecipeContract
from agent_os.domain.ingredients.embedding import EmbeddingProvider, SemanticMatch
from agent_os.domain.ingredients.envelope import (
    IngredientKind,
    IngredientStatus,
)
from agent_os.domain.ingredients.store import IngredientRepository
from agent_os.infrastructure.storage.ingredient_db import (
    get_ingredient_connection,
    init_ingredient_db,
)


def _pack_vector(vec: list[float]) -> bytes:
    """Pack a list of floats into binary format."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack_vector(blob: bytes, dim: int) -> list[float]:
    """Unpack binary format into a list of floats."""
    return list(struct.unpack(f"{dim}f", blob))


class IngredientVectorIndex:
    """Stores and queries normalized embeddings for recipe discovery."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_ingredient_db(self.db_path)

    def reindex_recipe(self, recipe: RecipeContract, provider: EmbeddingProvider) -> None:
        """Compute and persist the centroid embedding for a recipe and its intent examples."""
        texts = [recipe.description] + recipe.intent_examples
        vectors = provider.embed(texts)
        if not vectors:
            return

        dim = provider.dimension
        # Calculate mean vector across all intent examples and description
        mean_vec = [0.0] * dim
        for vec in vectors:
            for i in range(dim):
                mean_vec[i] += vec[i]
        norm = sum(x * x for x in mean_vec) ** 0.5
        if norm > 0:
            mean_vec = [x / norm for x in mean_vec]

        blob = _pack_vector(mean_vec)
        query = """
        INSERT INTO ingredient_vectors (
            ingredient_id, version, model_id, dim, content_hash, vector_blob
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ingredient_id, version, model_id) DO UPDATE SET
            dim = excluded.dim,
            content_hash = excluded.content_hash,
            vector_blob = excluded.vector_blob;
        """
        with get_ingredient_connection(self.db_path) as conn:
            conn.execute(
                query,
                (recipe.id, recipe.version, provider.model_id, dim, recipe.content_hash, blob),
            )

    def reindex_all(
        self,
        store: IngredientRepository,
        provider: EmbeddingProvider,
        force: bool = False,
    ) -> int:
        """Synchronize vector index with all candidate and active recipes in the repository."""
        recipes = store.list(kind=IngredientKind.RECIPE)
        usable_recipes = [
            r
            for r in recipes
            if isinstance(r, RecipeContract)
            and r.status in (IngredientStatus.CANDIDATE, IngredientStatus.ACTIVE)
        ]

        indexed_count = 0
        with get_ingredient_connection(self.db_path) as conn:
            for recipe in usable_recipes:
                if not force:
                    row = conn.execute(
                        "SELECT content_hash FROM ingredient_vectors "
                        "WHERE ingredient_id = ? AND version = ? AND model_id = ?;",
                        (recipe.id, recipe.version, provider.model_id),
                    ).fetchone()
                    if row is not None and row["content_hash"] == recipe.content_hash:
                        continue
                self.reindex_recipe(recipe, provider)
                indexed_count += 1

        return indexed_count

    def query_top_k(
        self,
        query: str,
        provider: EmbeddingProvider,
        k: int = 5,
    ) -> list[SemanticMatch]:
        """Perform brute-force cosine similarity search against indexed recipe vectors."""
        q_vec = provider.embed_query(query)
        dim = provider.dimension

        with get_ingredient_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT ingredient_id, version, vector_blob FROM ingredient_vectors "
                "WHERE model_id = ? AND dim = ?;",
                (provider.model_id, dim),
            ).fetchall()

        if not rows:
            return []

        matches: list[SemanticMatch] = []
        for r in rows:
            r_vec = _unpack_vector(r["vector_blob"], dim)
            score = sum(a * b for a, b in zip(q_vec, r_vec, strict=False))
            matches.append(
                SemanticMatch(
                    ingredient_id=r["ingredient_id"],
                    version=r["version"],
                    score=round(score, 4),
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:k]
