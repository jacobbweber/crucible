"""Intent resolver: dual retrieval, schema binding gate, and model adjudication."""

from enum import StrEnum
from typing import Any

import jsonschema
from pydantic import BaseModel, Field

from agent_os.domain.gateway import ChatMessage
from agent_os.domain.ingredients.contracts import RecipeContract
from agent_os.domain.ingredients.embedding import EmbeddingProvider
from agent_os.domain.ingredients.envelope import (
    IngredientStatus,
)
from agent_os.domain.ingredients.intent import TaskIntent
from agent_os.domain.ingredients.rules import validate_effect_alignment
from agent_os.domain.ingredients.store import IngredientRepository
from agent_os.domain.policy import ActionTier
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.structured import complete_structured
from agent_os.infrastructure.storage.ingredient_index import IngredientVectorIndex


class CandidateScore(BaseModel):
    """Scored recipe candidate combining signature agreement and semantic similarity."""

    recipe: RecipeContract
    signature_matched: bool
    semantic_score: float = 0.0
    fusion_score: float = 0.0


class BoundCandidate(BaseModel):
    """Recipe candidate that passed hard parameter schema and tool mounting gates."""

    recipe: RecipeContract
    score: CandidateScore
    bound_parameters: dict[str, Any] = Field(default_factory=dict)


class ResolutionVerdict(StrEnum):
    """Verdict of the intent resolution pipeline."""

    EXECUTE = "execute"
    COMPOSE = "compose"
    REJECTED = "rejected"


class ResolutionResult(BaseModel):
    """Final outcome of intent resolution."""

    verdict: ResolutionVerdict
    recipe: RecipeContract | None = None
    bound_parameters: dict[str, Any] = Field(default_factory=dict)
    candidates_considered: list[str] = Field(default_factory=list)
    reason: str = ""


class AdjudicationOutput(BaseModel):
    """Structured response from model adjudication."""

    selected_recipe_id: str
    rationale: str = ""


class IntentResolver:
    """Coordinates dual retrieval, hard binding gates, and structured adjudication."""

    def __init__(
        self,
        store: IngredientRepository,
        index: IngredientVectorIndex,
        provider: EmbeddingProvider,
        model_adapter: BaseModelAdapter | None = None,
    ) -> None:
        self.store = store
        self.index = index
        self.provider = provider
        self.model_adapter = model_adapter

    def retrieve_candidates(self, intent: TaskIntent, top_k: int = 5) -> list[CandidateScore]:
        """Union of relational matches on signature and top-k cosine similarity matches."""
        # 1. Relational match on capability signature
        relational = self.store.find_by_signature(
            verb=intent.verb,
            resource=intent.resource,
            scope=intent.scope,
        )
        relational_recipes: dict[str, RecipeContract] = {
            r.id: r
            for r in relational
            if isinstance(r, RecipeContract)
            and r.status in (IngredientStatus.CANDIDATE, IngredientStatus.ACTIVE)
        }

        # 2. Semantic matches on intent utterance
        semantic_matches = self.index.query_top_k(
            query=intent.normalized_utterance,
            provider=self.provider,
            k=top_k,
        )
        semantic_scores: dict[str, float] = {m.ingredient_id: m.score for m in semantic_matches}

        all_candidate_ids = set(relational_recipes.keys()) | set(semantic_scores.keys())
        scored: list[CandidateScore] = []

        sig = intent.to_capability_signature()
        for cid in all_candidate_ids:
            recipe = relational_recipes.get(cid)
            if recipe is None:
                fetched = self.store.get(cid)
                if not isinstance(fetched, RecipeContract):
                    continue
                if fetched.status not in (IngredientStatus.CANDIDATE, IngredientStatus.ACTIVE):
                    continue
                recipe = fetched

            matches_sig = recipe.capability.matches(sig)
            sem_score = semantic_scores.get(cid, 0.0)

            # Signature agreement outranks similarity (weight 10.0 vs <= 1.0)
            fusion = (10.0 if matches_sig else 0.0) + max(0.0, sem_score)
            scored.append(
                CandidateScore(
                    recipe=recipe,
                    signature_matched=matches_sig,
                    semantic_score=sem_score,
                    fusion_score=round(fusion, 4),
                )
            )

        scored.sort(key=lambda c: c.fusion_score, reverse=True)
        return scored

    def bind_candidate(
        self,
        candidate: CandidateScore,
        intent: TaskIntent,
        mounted_tools: set[str] | None,
        allowed_tier: ActionTier,
    ) -> BoundCandidate | None:
        """Evaluate hard gate: operation compatible, effect permitted, tools mounted."""
        recipe = candidate.recipe

        # Gate 0: Operation compatibility (verb and resource must align)
        if recipe.capability.verb != intent.verb:
            return None
        if recipe.capability.resource != intent.resource:
            return None

        # Gate 1: Effect alignment
        if not validate_effect_alignment(recipe.capability.effect, allowed_tier):
            return None

        # Gate 2: Required tool mounting
        if mounted_tools is not None:
            for tool_ref in recipe.tools:
                tool_name = tool_ref.split("@")[0]
                if tool_name not in mounted_tools and tool_ref not in mounted_tools:
                    return None

        # Gate 3: Schema validation and parameter population
        params = dict(intent.parameters)
        inputs_schema = recipe.inputs_schema
        properties = inputs_schema.get("properties", {})
        for prop_name, prop_spec in properties.items():
            if prop_name not in params and isinstance(prop_spec, dict) and "default" in prop_spec:
                params[prop_name] = prop_spec["default"]

        validator = jsonschema.Draft202012Validator(inputs_schema)
        errors = list(validator.iter_errors(params))
        if errors:
            return None

        return BoundCandidate(
            recipe=recipe,
            score=candidate,
            bound_parameters=params,
        )

    async def adjudicate(
        self,
        intent: TaskIntent,
        bound_candidates: list[BoundCandidate],
    ) -> ResolutionResult:
        """Decide execution path: 0 viable -> compose; 1 -> execute; 2-3 -> model choice."""
        if not bound_candidates:
            return ResolutionResult(
                verdict=ResolutionVerdict.COMPOSE,
                reason="No viable candidates satisfied signature, parameters, and tool bindings.",
            )

        if len(bound_candidates) == 1:
            chosen = bound_candidates[0]
            return ResolutionResult(
                verdict=ResolutionVerdict.EXECUTE,
                recipe=chosen.recipe,
                bound_parameters=chosen.bound_parameters,
                candidates_considered=[chosen.recipe.id],
                reason="Single unambiguous candidate matched and bound.",
            )

        # 2-3 candidates: model adjudication
        top_candidates = bound_candidates[:3]
        considered_ids = [c.recipe.id for c in top_candidates]

        if self.model_adapter is not None:
            options_desc = "\n".join(
                f"- '{c.recipe.id}': {c.recipe.description}" for c in top_candidates
            )
            prompt = (
                f"Given the user request: '{intent.normalized_utterance}'\n"
                f"Desired output: '{intent.desired_output}'\n\n"
                f"Which recipe best fulfills this request?\n{options_desc}\n"
                "- 'none': None of these recipes are suitable; compose a new one.\n"
            )
            messages = [
                ChatMessage(
                    role="system",
                    content="You select the exact recipe for a task.",
                ),
                ChatMessage(role="user", content=prompt),
            ]

            try:
                adjudication = await complete_structured(
                    self.model_adapter, messages, AdjudicationOutput
                )
                sel_id = adjudication.selected_recipe_id
                if sel_id != "none":
                    matched = next((c for c in top_candidates if c.recipe.id == sel_id), None)
                    if matched is not None:
                        return ResolutionResult(
                            verdict=ResolutionVerdict.EXECUTE,
                            recipe=matched.recipe,
                            bound_parameters=matched.bound_parameters,
                            candidates_considered=considered_ids,
                            reason=f"Model selected recipe '{sel_id}'.",
                        )
                return ResolutionResult(
                    verdict=ResolutionVerdict.REJECTED,
                    candidates_considered=considered_ids,
                    reason="Model adjudicated candidates as insufficient.",
                )
            except Exception:
                pass

        # Fallback if no model adapter: select top scored candidate
        highest = top_candidates[0]
        return ResolutionResult(
            verdict=ResolutionVerdict.EXECUTE,
            recipe=highest.recipe,
            bound_parameters=highest.bound_parameters,
            candidates_considered=considered_ids,
            reason="Selected top candidate by score.",
        )

    async def resolve(
        self,
        intent: TaskIntent,
        mounted_tools: set[str] | None = None,
        allowed_tier: ActionTier = ActionTier.DESTRUCTIVE,
    ) -> ResolutionResult:
        """Full pipeline: Retrieve -> Bind -> Adjudicate."""
        candidates = self.retrieve_candidates(intent)
        bound: list[BoundCandidate] = []
        for c in candidates:
            b = self.bind_candidate(c, intent, mounted_tools, allowed_tier)
            if b is not None:
                bound.append(b)

        return await self.adjudicate(intent, bound)
