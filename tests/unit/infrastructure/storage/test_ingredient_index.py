"""Unit tests for IngredientVectorIndex, semantic retrieval, and seeding."""

from pathlib import Path

import pytest

from agent_os.domain.ingredients.default_recipes import get_default_recipe_contracts
from agent_os.domain.ingredients.envelope import IngredientKind, IngredientStatus
from agent_os.domain.ingredients.seeding import seed_default_ingredients
from agent_os.infrastructure.embedding.fastembed_provider import (
    DeterministicMockEmbeddingProvider,
)
from agent_os.infrastructure.storage.ingredient_index import IngredientVectorIndex
from agent_os.infrastructure.storage.ingredient_store import SqliteIngredientStore


@pytest.fixture
def mock_provider() -> DeterministicMockEmbeddingProvider:
    return DeterministicMockEmbeddingProvider(dimension=32)


@pytest.fixture
def test_setup(tmp_path: Path) -> tuple[SqliteIngredientStore, IngredientVectorIndex]:
    db_path = tmp_path / "ingredients.db"
    store = SqliteIngredientStore(db_path=db_path)
    index = IngredientVectorIndex(db_path=db_path)
    return store, index


def test_index_reindex_and_top_k_query(
    test_setup: tuple[SqliteIngredientStore, IngredientVectorIndex],
    mock_provider: DeterministicMockEmbeddingProvider,
) -> None:
    """Vector index computes centroids and returns top-k semantic matches."""
    store, index = test_setup
    recipes = get_default_recipe_contracts()

    from agent_os.domain.ingredients.builtin import get_builtin_tool_contracts

    for tool in get_builtin_tool_contracts():
        store.save(tool)

    # Save two recipes
    store.save(recipes[0])  # self_health_audit
    store.save(recipes[1])  # wiki_capture_note

    indexed_count = index.reindex_all(store, mock_provider)
    assert indexed_count == 2

    # Second reindex without force should skip because content_hash is unchanged
    assert index.reindex_all(store, mock_provider, force=False) == 0

    # Query with identical wording to intent example should match high
    matches = index.query_top_k("how healthy is the system", mock_provider, k=5)
    assert len(matches) == 2
    assert matches[0].ingredient_id == "self_health_audit"
    assert matches[0].score > 0.0


def test_seed_default_ingredients_idempotent(
    test_setup: tuple[SqliteIngredientStore, IngredientVectorIndex],
    mock_provider: DeterministicMockEmbeddingProvider,
) -> None:
    """Seeding populates default tools, recipes, and vector index idempotently."""
    store, index = test_setup

    seed_default_ingredients(store, index, mock_provider)

    tools = store.list(kind=IngredientKind.TOOL)
    recipes = store.list(kind=IngredientKind.RECIPE)
    assert len(tools) >= 8
    assert len(recipes) >= 6

    # Verify every recipe is active
    for r in recipes:
        assert r.status == IngredientStatus.ACTIVE

    # Running seed again does not duplicate or fail
    seed_default_ingredients(store, index, mock_provider)
    assert len(store.list(kind=IngredientKind.TOOL)) == len(tools)
    assert len(store.list(kind=IngredientKind.RECIPE)) == len(recipes)

    # Query top-k against seeded index
    top_matches = index.query_top_k("read README.md", mock_provider, k=3)
    assert len(top_matches) > 0
    assert any(m.ingredient_id == "workspace_read_file" for m in top_matches)
