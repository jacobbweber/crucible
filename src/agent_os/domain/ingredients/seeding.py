"""Provisioning and seeding utilities for default built-in ingredients and recipes."""

from agent_os.domain.ingredients.builtin import get_builtin_tool_contracts
from agent_os.domain.ingredients.default_recipes import get_default_recipe_contracts
from agent_os.domain.ingredients.embedding import EmbeddingProvider
from agent_os.domain.ingredients.store import IngredientRepository
from agent_os.infrastructure.storage.ingredient_index import IngredientVectorIndex


def seed_default_ingredients(
    store: IngredientRepository,
    index: IngredientVectorIndex | None = None,
    provider: EmbeddingProvider | None = None,
) -> None:
    """Idempotently seed default tool contracts and migrated recipes into store and index."""
    # Seed built-in tools first
    for tool in get_builtin_tool_contracts():
        existing = store.get(tool.id, tool.version)
        if existing is None:
            store.save(tool)

    # Seed default recipes
    for recipe in get_default_recipe_contracts():
        existing = store.get(recipe.id, recipe.version)
        if existing is None:
            store.save(recipe)

    # Synchronize vector index if provided
    if index is not None and provider is not None:
        index.reindex_all(store, provider)
