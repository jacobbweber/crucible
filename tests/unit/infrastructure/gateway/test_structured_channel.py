"""Hermetic tests for the structured gateway channel (ADR-0015 §4.1).

SSE fixtures mirror shapes captured live: vLLM streams tool-call argument fragments
keyed by index; Ollama emits each call whole in one delta.
"""

import json
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import (
    ChatMessage,
    CompletionRequest,
    ResponseSchema,
    StreamChunk,
    ToolCallPart,
    ToolSpec,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.openai_payload import build_payload
from agent_os.infrastructure.gateway.structured import (
    StructuredOutputError,
    complete_structured,
    inline_refs,
    parse_tool_arguments,
    tool_spec_for,
)
from agent_os.infrastructure.gateway.vllm import VllmAdapter

SPEC = ToolSpec(
    name="fulfill_request",
    description="Dispatch a task.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


def _sse(*events: dict[str, Any]) -> str:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


def _choice(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {"choices": [{"delta": delta, "finish_reason": finish}]}


async def _run(sse: str) -> list[StreamChunk]:
    adapter = VllmAdapter(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=sse)))
    req = CompletionRequest(messages=[ChatMessage(role="user", content="x")], tools=[SPEC])
    return [c async for c in adapter.complete(req)]


def test_payload_maps_tools_named_choice_and_response_schema() -> None:
    schema = ResponseSchema(name="intent", schema={"type": "object"})
    req = CompletionRequest(
        messages=[ChatMessage(role="user", content="x")],
        tools=[SPEC],
        tool_choice="fulfill_request",
        response_schema=schema,
    )
    payload = build_payload(req, AppConfig(), 256)
    assert payload["tools"][0]["function"]["name"] == "fulfill_request"
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "fulfill_request"}}
    assert payload["response_format"]["json_schema"]["name"] == "intent"
    assert payload["response_format"]["json_schema"]["strict"] is True


def test_payload_round_trips_assistant_tool_calls() -> None:
    call = ToolCallPart(id="c1", name="fulfill_request", arguments='{"path": "M:/"}')
    req = CompletionRequest(
        messages=[
            ChatMessage(role="assistant", parts=[call]),
            ChatMessage(role="tool", content="ok", tool_call_id="c1", name="fulfill_request"),
        ]
    )
    msgs = build_payload(req, AppConfig(), 256)["messages"]
    assert msgs[0]["content"] is None
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"path": "M:/"}'
    assert msgs[1]["tool_call_id"] == "c1"


@pytest.mark.asyncio
async def test_vllm_fragmented_tool_call_is_assembled_once() -> None:
    sse = _sse(
        _choice({"role": "assistant", "content": ""}),
        _choice(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "t1",
                        "function": {"name": "fulfill_request", "arguments": ""},
                    }
                ]
            }
        ),
        _choice({"tool_calls": [{"index": 0, "function": {"arguments": '{"path": "M:'}}]}),
        _choice(
            {"tool_calls": [{"index": 0, "function": {"arguments": '/Media"}'}}]}, "tool_calls"
        ),
    )
    chunks = await _run(sse)
    calls = [c for ch in chunks for c in ch.tool_calls]
    assert len(calls) == 1
    assert calls[0].id == "t1"
    assert json.loads(calls[0].arguments) == {"path": "M:/Media"}
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_ollama_whole_tool_call_and_parallel_calls() -> None:
    sse = _sse(
        _choice(
            {
                "tool_calls": [
                    {
                        "id": "a",
                        "index": 0,
                        "function": {"name": "fulfill_request", "arguments": "{}"},
                    },
                    {
                        "id": "b",
                        "index": 1,
                        "function": {"name": "fulfill_request", "arguments": "{}"},
                    },
                ]
            }
        ),
        _choice({}, "tool_calls"),
    )
    calls = [c for ch in await _run(sse) for c in ch.tool_calls]
    assert [c.id for c in calls] == ["a", "b"]


@pytest.mark.asyncio
async def test_tool_calls_emitted_when_stream_ends_without_finish_reason() -> None:
    call = {"index": 0, "id": "z", "function": {"name": "fulfill_request", "arguments": "{}"}}
    sse = _sse(_choice({"tool_calls": [call]}))
    chunks = await _run(sse)
    assert chunks[-1].finish_reason == "tool_calls"
    assert chunks[-1].tool_calls[0].id == "z"


class Intent(BaseModel):
    verb: str
    path: str


class ScriptedAdapter(BaseModelAdapter):
    """Returns queued text replies and records requests."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        self.requests.append(request)
        yield StreamChunk(delta=self.replies.pop(0), finish_reason="stop")


@pytest.mark.asyncio
async def test_complete_structured_sends_schema_and_validates() -> None:
    adapter = ScriptedAdapter(['{"verb": "list", "path": "M:/"}'])
    out = await complete_structured(adapter, [ChatMessage(role="user", content="x")], Intent)
    assert out == Intent(verb="list", path="M:/")
    sent = adapter.requests[0].response_schema
    assert sent is not None and sent.name == "Intent"


@pytest.mark.asyncio
async def test_complete_structured_retries_with_validation_feedback() -> None:
    adapter = ScriptedAdapter(['{"verb": "list"}', '{"verb": "list", "path": "D:/"}'])
    out = await complete_structured(adapter, [ChatMessage(role="user", content="x")], Intent)
    assert out.path == "D:/"
    assert "failed schema validation" in adapter.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_complete_structured_raises_typed_error_without_fallback() -> None:
    adapter = ScriptedAdapter(["not json", "```json\n{}\n```"])
    with pytest.raises(StructuredOutputError) as err:
        await complete_structured(adapter, [ChatMessage(role="user", content="x")], Intent)
    assert err.value.raw_output.startswith("```json")


def test_parse_tool_arguments_validates() -> None:
    good = ToolCallPart(id="1", name="t", arguments='{"verb": "read", "path": "a"}')
    assert parse_tool_arguments(good, Intent).verb == "read"
    with pytest.raises(StructuredOutputError):
        parse_tool_arguments(ToolCallPart(id="2", name="t", arguments="{}"), Intent)


class Inner(BaseModel):
    kind: Literal["a", "b"]


class Outer(BaseModel):
    inner: Inner = Field(description="nested signature")


class Node(BaseModel):
    child: "Node | None" = None


def test_model_facing_schemas_are_self_contained() -> None:
    params = tool_spec_for(Outer, "t", "d").parameters
    assert "$defs" not in json.dumps(params) and "$ref" not in json.dumps(params)
    inner = params["properties"]["inner"]
    assert inner["type"] == "object"
    assert inner["description"] == "nested signature"
    assert inner["properties"]["kind"]["enum"] == ["a", "b"]


def test_recursive_models_are_rejected() -> None:
    with pytest.raises(ValueError, match="Recursive"):
        inline_refs(Node.model_json_schema())
