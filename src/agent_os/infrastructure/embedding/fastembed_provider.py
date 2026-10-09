"""In-process embedding provider implementations using FastEmbed and deterministic mock."""

import hashlib
from pathlib import Path
from typing import Any

from agent_os.domain.ingredients.embedding import EmbeddingProvider


class FastEmbedProvider(EmbeddingProvider):
    """In-process CPU embedding provider using ONNX runtime via FastEmbed."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        cache_dir: Path | str | None = None,
        dimension: int = 384,
    ) -> None:
        self._model_name = model_name
        self._cache_dir = str(cache_dir) if cache_dir is not None else None
        self._dimension = dimension
        self._model: Any = None

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(
                model_name=self._model_name,
                cache_dir=self._cache_dir,
            )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Compute normalized vector embeddings for a list of document texts."""
        if not texts:
            return []
        model = self._ensure_model()
        vectors: list[list[float]] = []
        for vec in model.embed(texts):
            # Normalize to unit length
            norm = sum(x * x for x in vec) ** 0.5
            if norm > 0:
                vectors.append([x / norm for x in vec])
            else:
                vectors.append(list(vec))
        return vectors

    def embed_query(self, query: str) -> list[float]:
        """Compute normalized vector embedding for a single search query."""
        model = self._ensure_model()
        # FastEmbed's query_embed uses query instructions where supported (e.g. BGE)
        raw_iter = model.query_embed([query])
        vec = next(iter(raw_iter))
        norm = sum(x * x for x in vec) ** 0.5
        if norm > 0:
            return [x / norm for x in vec]
        return list(vec)


class DeterministicMockEmbeddingProvider(EmbeddingProvider):
    """Deterministic, hermetic embedding provider for unit tests without ONNX dependencies."""

    def __init__(self, dimension: int = 32, model_id: str = "mock-embed-32") -> None:
        self._dimension = dimension
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    def _hash_to_vec(self, text: str) -> list[float]:
        # Generate pseudo-vector from text hash
        vec: list[float] = []
        clean = text.strip().lower()
        for i in range(self._dimension):
            h = hashlib.sha256(f"{clean}:{i}".encode()).digest()
            val = int.from_bytes(h[:4], "big", signed=True) / (2**31)
            vec.append(val)
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec] if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_to_vec(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        return self._hash_to_vec(query)
