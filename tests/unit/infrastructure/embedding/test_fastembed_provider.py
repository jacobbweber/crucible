"""Unit tests for FastEmbedProvider and DeterministicMockEmbeddingProvider."""

from pathlib import Path

from agent_os.infrastructure.embedding.fastembed_provider import (
    DeterministicMockEmbeddingProvider,
    FastEmbedProvider,
)


def test_deterministic_mock_provider() -> None:
    """Mock provider produces deterministic unit-length vectors."""
    provider = DeterministicMockEmbeddingProvider(dimension=16)
    assert provider.model_id == "mock-embed-32"
    assert provider.dimension == 16

    vecs = provider.embed(["hello world", "test query"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 16

    # Unit normalized
    norm = sum(x * x for x in vecs[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-5

    # Query embedding is identical for same text
    q_vec = provider.embed_query("hello world")
    assert q_vec == vecs[0]


def test_fastembed_provider_contract_properties(tmp_path: Path) -> None:
    """FastEmbedProvider exposes model metadata before loading."""
    provider = FastEmbedProvider(
        model_name="BAAI/bge-small-en-v1.5",
        cache_dir=tmp_path / "cache",
        dimension=384,
    )
    assert provider.model_id == "BAAI/bge-small-en-v1.5"
    assert provider.dimension == 384
    assert provider._model is None
