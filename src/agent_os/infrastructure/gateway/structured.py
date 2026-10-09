"""Typed structured-output helpers over any BaseModelAdapter.

This is the only sanctioned path for kernel code to obtain machine-readable data from a
model (ADR-0015 §4.1): JSON-schema constrained decoding, Pydantic validation, one retry
carrying the validation error, then a typed failure. No regex or brace-hunting fallbacks.
"""

import copy
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent_os.domain.gateway import (
    ChatMessage,
    CompletionRequest,
    ResponseSchema,
    ThinkingLevel,
    ToolCallPart,
    ToolSpec,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """Raised when a model cannot produce schema-valid output within the retry budget."""

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


class CollectedResponse(BaseModel):
    """A fully drained completion stream."""

    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCallPart] = []
    finish_reason: str | None = None


async def collect(adapter: BaseModelAdapter, request: CompletionRequest) -> CollectedResponse:
    """Drain a completion stream into text, reasoning, and assembled tool calls."""
    text: list[str] = []
    reasoning: list[str] = []
    calls: list[ToolCallPart] = []
    finish: str | None = None
    async for chunk in adapter.complete(request):
        text.append(chunk.delta)
        reasoning.append(chunk.reasoning)
        calls.extend(chunk.tool_calls)
        finish = chunk.finish_reason or finish
    return CollectedResponse(
        text="".join(text), reasoning="".join(reasoning), tool_calls=calls, finish_reason=finish
    )


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a JSON Schema with every local `$ref` expanded and `$defs` removed.

    Live finding (Phase 18): vLLM and Ollama targets do not follow `$ref` inside tool
    parameter schemas and double-encode nested objects as strings. Model-facing schemas
    must therefore be self-contained. Recursive models are rejected.
    """
    defs: dict[str, Any] = schema.get("$defs", {})

    def resolve(node: Any, trail: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(n, trail) for n in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            if name in trail:
                raise ValueError(f"Recursive schema reference '{name}' is not model-safe")
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            return {**resolve(copy.deepcopy(defs[name]), (*trail, name)), **siblings}
        return {k: resolve(v, trail) for k, v in node.items() if k != "$defs"}

    resolved: dict[str, Any] = resolve(schema, ())
    return resolved


def schema_for(model: type[BaseModel], name: str | None = None) -> ResponseSchema:
    """Build a self-contained ResponseSchema from a Pydantic model."""
    return ResponseSchema(
        name=name or model.__name__, schema=inline_refs(model.model_json_schema())
    )


def tool_spec_for(model: type[BaseModel], name: str, description: str) -> ToolSpec:
    """Build a native ToolSpec whose self-contained arguments schema mirrors a Pydantic model."""
    return ToolSpec(
        name=name, description=description, parameters=inline_refs(model.model_json_schema())
    )


def parse_tool_arguments(call: ToolCallPart, model: type[T]) -> T:
    """Validate a tool call's JSON arguments; raise StructuredOutputError on mismatch."""
    try:
        return model.model_validate_json(call.arguments)
    except ValidationError as exc:
        raise StructuredOutputError(
            f"Tool '{call.name}' arguments failed validation: {exc}", call.arguments
        ) from exc


async def complete_structured(
    adapter: BaseModelAdapter,
    messages: list[ChatMessage],
    output_model: type[T],
    *,
    schema_name: str | None = None,
    thinking_level: ThinkingLevel = ThinkingLevel.NONE,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    retries: int = 1,
) -> T:
    """Request schema-constrained output and return a validated model instance."""
    schema = schema_for(output_model, schema_name)
    convo = list(messages)
    last_raw = ""
    for _attempt in range(retries + 1):
        request = CompletionRequest(
            messages=convo,
            response_schema=schema,
            thinking_level=thinking_level,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        last_raw = (await collect(adapter, request)).text.strip()
        try:
            return output_model.model_validate_json(last_raw)
        except ValidationError as exc:
            convo = [
                *convo,
                ChatMessage(role="assistant", content=last_raw or "(empty)"),
                ChatMessage(
                    role="user",
                    content=(
                        "Your previous output failed schema validation:\n"
                        f"{str(exc)[:1500]}\n"
                        "Return only a JSON object that satisfies the schema."
                    ),
                ),
            ]
    raise StructuredOutputError(
        f"{output_model.__name__}: no schema-valid output after {retries + 1} attempts",
        last_raw,
    )
