"""Typed contracts for ingredients: Tools, Context Sources, Model Profiles, Runbooks, Recipes."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent_os.domain.ingredients.envelope import (
    IngredientEnvelope,
    IngredientKind,
    compute_sha256,
)
from agent_os.domain.ingredients.signature import CapabilitySignature


class ContractExample(BaseModel):
    """A concrete example input/expected output pair validating a tool or recipe."""

    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
    description: str = ""


class ToolRuntime(StrEnum):
    """Runtime execution environment hosting a tool."""

    BUILTIN = "builtin"
    MCP_HUB = "mcp_hub"
    MCP_EXTERNAL = "mcp_external"


def _validate_json_schema(schema: dict[str, Any], field_name: str) -> dict[str, Any]:
    """Ensure schema is a dict representing a valid typed JSON Schema object."""
    if not isinstance(schema, dict) or not schema:
        raise ValueError(f"{field_name} must be a non-empty JSON schema dict.")
    if schema.get("type") not in ("object", "array", "string", "integer", "number", "boolean"):
        raise ValueError(f"{field_name} must declare a valid JSON schema 'type'.")
    if schema.get("type") == "object" and "properties" not in schema:
        raise ValueError(f"{field_name} of type 'object' must define 'properties'.")
    return schema


class ToolContract(IngredientEnvelope):
    """Contract specification for an agent capability tool."""

    kind: IngredientKind = IngredientKind.TOOL
    capability: CapabilitySignature
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    examples: list[ContractExample] = Field(min_length=1)
    runtime: ToolRuntime = ToolRuntime.BUILTIN

    @field_validator("input_schema")
    @classmethod
    def _validate_inputs(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(v, "input_schema")

    @field_validator("output_schema")
    @classmethod
    def _validate_outputs(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(v, "output_schema")

    def model_post_init(self, __context: Any) -> None:
        """Compute content hash if not provided."""
        if not self.content_hash:
            data = {
                "id": self.id,
                "version": self.version,
                "capability": self.capability.canonical_str(),
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "runtime": self.runtime.value,
            }
            self.content_hash = compute_sha256(data)


class ContextSourceKind(StrEnum):
    """Known storage backend sources providing context."""

    FACTS = "facts"
    VAULT = "vault"
    SESSION_HISTORY = "session_history"
    SYSTEM_INFO = "system_info"


class ContextSourceContract(IngredientEnvelope):
    """Contract specification for a parameterizable context retrieval source."""

    kind: IngredientKind = IngredientKind.CONTEXT_SOURCE
    source: ContextSourceKind
    query: str = Field(min_length=1)
    max_tokens: int = Field(default=1000, ge=1)

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            data = {
                "id": self.id,
                "version": self.version,
                "source": self.source.value,
                "query": self.query,
                "max_tokens": self.max_tokens,
            }
            self.content_hash = compute_sha256(data)


class ThinkingLevel(StrEnum):
    """Reasoning effort budget allocated to model execution."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelProfile(IngredientEnvelope):
    """Configuration profile targeting a model's role, sampling, and reasoning parameters."""

    kind: IngredientKind = IngredientKind.MODEL_PROFILE
    role: str = Field(min_length=1)
    thinking_level: ThinkingLevel = ThinkingLevel.NONE
    max_tokens: int = Field(default=2048, ge=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            data = {
                "id": self.id,
                "version": self.version,
                "role": self.role,
                "thinking_level": self.thinking_level.value,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            self.content_hash = compute_sha256(data)


class RunbookEngine(StrEnum):
    """Execution engine coordinating runbook steps."""

    DIRECT = "direct"
    REACT = "react"
    PLAN_EXECUTE_VERIFY = "plan_execute_verify"
    STATEGRAPH = "stategraph"


class RunbookStep(BaseModel):
    """An individual execution step binding tool invocation to recipe state."""

    step_id: str = Field(min_length=1)
    tool_ref: str = Field(pattern=r"^[a-z0-9_-]+@\d+$")
    input_bindings: dict[str, str] = Field(default_factory=dict)
    description: str = ""


class RunbookContract(IngredientEnvelope):
    """Multi-step orchestration workflow contract."""

    kind: IngredientKind = IngredientKind.RUNBOOK
    engine: RunbookEngine = RunbookEngine.DIRECT
    steps: list[RunbookStep] = Field(default_factory=list)
    max_turns: int = Field(default=10, ge=1)
    timeout_seconds: int = Field(default=300, ge=1)

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            data = {
                "id": self.id,
                "version": self.version,
                "engine": self.engine.value,
                "steps": [s.model_dump() for s in self.steps],
                "max_turns": self.max_turns,
                "timeout_seconds": self.timeout_seconds,
            }
            self.content_hash = compute_sha256(data)


class AcceptanceCheckType(StrEnum):
    """Type of assertion verifying successful recipe execution."""

    JSON_SCHEMA = "json_schema"
    DETERMINISTIC = "deterministic"
    RUBRIC_JUDGE = "rubric_judge"


class AcceptanceCheck(BaseModel):
    """Verification check evaluated post-execution."""

    check_type: AcceptanceCheckType
    rule: str = Field(min_length=1)
    description: str = ""


class RecipeStats(BaseModel):
    """Runtime execution statistics tracking reliability and promotion readiness."""

    run_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    last_run: datetime | None = None


class RecipeContract(IngredientEnvelope):
    """Contract-first composition combining tools, context, model, and workflow."""

    kind: IngredientKind = IngredientKind.RECIPE
    capability: CapabilitySignature
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    tools: list[str] = Field(default_factory=list)
    context_sources: list[str] = Field(default_factory=list)
    model_profile: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+@\d+$")
    runbook: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+@\d+$")
    acceptance: list[AcceptanceCheck] = Field(default_factory=list)
    intent_examples: list[str] = Field(default_factory=list)
    stats: RecipeStats = Field(default_factory=RecipeStats)

    @field_validator("inputs_schema")
    @classmethod
    def _validate_inputs(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(v, "inputs_schema")

    @field_validator("outputs_schema")
    @classmethod
    def _validate_outputs(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_json_schema(v, "outputs_schema")

    @field_validator("tools", "context_sources")
    @classmethod
    def _validate_pinned_refs(cls, refs: list[str]) -> list[str]:
        for ref in refs:
            IngredientEnvelope.parse_pinned_ref(ref)
        return refs

    def model_post_init(self, __context: Any) -> None:
        if not self.content_hash:
            data = {
                "id": self.id,
                "version": self.version,
                "capability": self.capability.canonical_str(),
                "inputs_schema": self.inputs_schema,
                "outputs_schema": self.outputs_schema,
                "tools": sorted(self.tools),
                "context_sources": sorted(self.context_sources),
                "model_profile": self.model_profile,
                "runbook": self.runbook,
            }
            self.content_hash = compute_sha256(data)
