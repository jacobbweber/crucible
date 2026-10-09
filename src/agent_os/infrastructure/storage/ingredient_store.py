"""SQLite-backed implementation of the IngredientRepository interface."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_os.domain.ingredients.contracts import (
    ContextSourceContract,
    ModelProfile,
    RecipeContract,
    RunbookContract,
    ToolContract,
)
from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientKind,
    IngredientStatus,
)
from agent_os.domain.ingredients.rules import (
    validate_canonical_id,
    validate_recipe_contract,
    validate_tool_contract,
)
from agent_os.domain.ingredients.store import IngredientRepository
from agent_os.domain.ingredients.vocabulary import (
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)
from agent_os.infrastructure.storage.ingredient_db import (
    get_ingredient_connection,
    init_ingredient_db,
)


def _deserialize_ingredient(kind_str: str, contract_json: str) -> IngredientEnvelope:
    """Deserialize contract JSON into the corresponding concrete model."""
    data = json.loads(contract_json)
    kind = IngredientKind(kind_str)
    if kind == IngredientKind.TOOL:
        return ToolContract.model_validate(data)
    if kind == IngredientKind.RECIPE:
        return RecipeContract.model_validate(data)
    if kind == IngredientKind.CONTEXT_SOURCE:
        return ContextSourceContract.model_validate(data)
    if kind == IngredientKind.MODEL_PROFILE:
        return ModelProfile.model_validate(data)
    if kind == IngredientKind.RUNBOOK:
        return RunbookContract.model_validate(data)
    return IngredientEnvelope.model_validate(data)


class SqliteIngredientStore(IngredientRepository):
    """SQLite repository persisting and querying versioned ingredients."""

    def __init__(
        self,
        db_path: Path,
        registry: ResourceVocabularyRegistry | None = None,
    ) -> None:
        self.db_path = db_path
        self.registry = registry or ResourceVocabularyRegistry.default_registry()
        init_ingredient_db(self.db_path)

    def save(self, ingredient: IngredientEnvelope) -> IngredientEnvelope:
        """Validate and upsert an ingredient record into ingredients.db."""
        validate_canonical_id(ingredient.id)

        if isinstance(ingredient, ToolContract):
            validate_tool_contract(ingredient, registry=self.registry)
        elif isinstance(ingredient, RecipeContract):
            validate_recipe_contract(ingredient, resolver=self.get, registry=self.registry)

        verb = resource = scope = effect = capability_str = None
        if isinstance(ingredient, (ToolContract, RecipeContract)):
            cap = ingredient.capability
            verb = cap.verb.value
            resource = cap.resource
            scope = cap.scope.value
            effect = cap.effect.value
            capability_str = cap.canonical_str()

        now_iso = datetime.now(UTC).isoformat()
        contract_json = json.dumps(ingredient.model_dump(mode="json"))

        query = """
        INSERT INTO ingredients (
            id, version, kind, status, capability, verb, resource, scope, effect,
            description, contract_json, content_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id, version) DO UPDATE SET
            status = excluded.status,
            capability = excluded.capability,
            verb = excluded.verb,
            resource = excluded.resource,
            scope = excluded.scope,
            effect = excluded.effect,
            description = excluded.description,
            contract_json = excluded.contract_json,
            content_hash = excluded.content_hash,
            updated_at = excluded.updated_at;
        """

        with get_ingredient_connection(self.db_path) as conn:
            conn.execute(
                query,
                (
                    ingredient.id,
                    ingredient.version,
                    ingredient.kind.value,
                    ingredient.status.value,
                    capability_str,
                    verb,
                    resource,
                    scope,
                    effect,
                    ingredient.description,
                    contract_json,
                    ingredient.content_hash,
                    now_iso,
                    now_iso,
                ),
            )
        return ingredient

    def get(self, ingredient_id: str, version: int | None = None) -> IngredientEnvelope | None:
        """Retrieve ingredient by ID and optional version. Defaults to highest version."""
        with get_ingredient_connection(self.db_path) as conn:
            if version is not None:
                row = conn.execute(
                    "SELECT kind, contract_json FROM ingredients WHERE id = ? AND version = ?;",
                    (ingredient_id, version),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT kind, contract_json FROM ingredients WHERE id = ? "
                    "ORDER BY version DESC LIMIT 1;",
                    (ingredient_id,),
                ).fetchone()

        if row is None:
            return None
        return _deserialize_ingredient(row["kind"], row["contract_json"])

    def list(
        self,
        kind: IngredientKind | None = None,
        status: IngredientStatus | None = None,
    ) -> list[IngredientEnvelope]:
        """List ingredients matching optional kind and status filters."""
        query = "SELECT kind, contract_json FROM ingredients WHERE 1=1"
        params: list[Any] = []
        if kind is not None:
            query += " AND kind = ?"
            params.append(kind.value)
        if status is not None:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY id ASC, version DESC;"

        with get_ingredient_connection(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        return [_deserialize_ingredient(r["kind"], r["contract_json"]) for r in rows]

    def find_by_signature(
        self,
        verb: Verb,
        resource: str,
        scope: Scope,
    ) -> list[IngredientEnvelope]:
        """Lookup active or candidate ingredients matching capability signature."""
        query = """
        SELECT kind, contract_json FROM ingredients
        WHERE verb = ? AND resource = ? AND scope = ?
          AND status IN ('candidate', 'active')
        ORDER BY version DESC;
        """
        with get_ingredient_connection(self.db_path) as conn:
            rows = conn.execute(query, (verb.value, resource, scope.value)).fetchall()

        return [_deserialize_ingredient(r["kind"], r["contract_json"]) for r in rows]
