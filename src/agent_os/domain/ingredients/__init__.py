"""Contract-first ingredients subsystem: typed schemas, capability signatures, and vocabulary."""

from agent_os.domain.ingredients.builtin import get_builtin_tool_contracts
from agent_os.domain.ingredients.contracts import (
    AcceptanceCheck,
    AcceptanceCheckType,
    ContextSourceContract,
    ContextSourceKind,
    ContractExample,
    ModelProfile,
    RecipeContract,
    RecipeStats,
    RunbookContract,
    RunbookEngine,
    RunbookStep,
    ThinkingLevel,
    ToolContract,
    ToolRuntime,
)
from agent_os.domain.ingredients.default_recipes import get_default_recipe_contracts
from agent_os.domain.ingredients.embedding import EmbeddingProvider, SemanticMatch
from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientKind,
    IngredientStatus,
    Provenance,
    canonical_json_bytes,
    compute_sha256,
)
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.rules import (
    CraftingRuleViolation,
    validate_canonical_id,
    validate_effect_alignment,
    validate_recipe_contract,
    validate_schema_structure,
    validate_tool_contract,
)
from agent_os.domain.ingredients.seeding import seed_default_ingredients
from agent_os.domain.ingredients.signature import CapabilitySignature
from agent_os.domain.ingredients.store import IngredientRepository
from agent_os.domain.ingredients.vocabulary import (
    EFFECT_DESCRIPTIONS,
    SCOPE_DESCRIPTIONS,
    VERB_DESCRIPTIONS,
    Effect,
    ResourceEntry,
    ResourceVocabularyRegistry,
    Scope,
    Verb,
)

__all__ = [
    "AcceptanceCheck",
    "AcceptanceCheckType",
    "CapabilitySignature",
    "ContextSourceContract",
    "ContextSourceKind",
    "ContractExample",
    "CraftingRuleViolation",
    "EFFECT_DESCRIPTIONS",
    "Effect",
    "EmbeddingProvider",
    "IngredientEnvelope",
    "IngredientKind",
    "IngredientRepository",
    "IngredientStatus",
    "ModelProfile",
    "Provenance",
    "RecipeContract",
    "RecipeStats",
    "ResourceEntry",
    "ResourceVocabularyRegistry",
    "RunbookContract",
    "RunbookEngine",
    "RunbookStep",
    "SCOPE_DESCRIPTIONS",
    "Scope",
    "SemanticMatch",
    "TaskIntent",
    "ThinkingLevel",
    "ToolContract",
    "ToolRuntime",
    "VERB_DESCRIPTIONS",
    "Verb",
    "canonical_json_bytes",
    "compute_sha256",
    "get_builtin_tool_contracts",
    "get_default_recipe_contracts",
    "seed_default_ingredients",
    "validate_canonical_id",
    "validate_effect_alignment",
    "validate_recipe_contract",
    "validate_schema_structure",
    "validate_tool_contract",
]
