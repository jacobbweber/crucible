"""Unit tests for vLLM streaming model adapter using httpx.MockTransport."""

import json
from typing import Any

import httpx
import pytest

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import ChatMessage, CompletionRequest, StreamChunk
from agent_os.infrastructure.gateway.vllm import VllmAdapter


@pytest.mark.asyncio
async def test_vllm_adapter_streaming_success() -> None:
    """Verify mock SSE stream yields 3 chunks in exact order and exits on [DONE]."""
    sse_data = (
        'data: {"choices": [{"delta": {"content": "Hello"}, "finish_reason": null}]}\n\n'
        'data: {"choices": [{"delta": {"content": " world"}, "finish_reason": null}]}\n\n'
        'data: {"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers.get("authorization") == "Bearer EMPTY"
        return httpx.Response(200, text=sse_data)

    adapter = VllmAdapter(transport=httpx.MockTransport(handler))
    request = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
    )

    chunks: list[StreamChunk] = []
    async for chunk in adapter.complete(request):
        chunks.append(chunk)

    assert len(chunks) == 3
    assert chunks[0].delta == "Hello"
    assert chunks[0].finish_reason is None
    assert chunks[1].delta == " world"
    assert chunks[1].finish_reason is None
    assert chunks[2].delta == "!"
    assert chunks[2].finish_reason == "stop"


@pytest.mark.asyncio
async def test_vllm_adapter_context_window_clamp() -> None:
    """Verify max_tokens exceeding config.vllm_context_window is clamped."""
    captured_payload: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_payload
        captured_payload = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, text="data: [DONE]\n\n")

    config = AppConfig(vllm_context_window=2048)
    adapter = VllmAdapter(config=config, transport=httpx.MockTransport(handler))
    request = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        max_tokens=10000,
    )

    chunks = [chunk async for chunk in adapter.complete(request)]
    assert chunks == []
    assert captured_payload["max_tokens"] == 2048


@pytest.mark.asyncio
async def test_vllm_adapter_http_error_handling() -> None:
    """Verify HTTP 500 error raises RuntimeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    adapter = VllmAdapter(transport=httpx.MockTransport(handler))
    request = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
    )

    with pytest.raises(RuntimeError, match="500"):
        async for _ in adapter.complete(request):
            pass


@pytest.mark.asyncio
async def test_vllm_adapter_connection_timeout() -> None:
    """Verify httpx.TimeoutException propagates cleanly as a RuntimeError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    adapter = VllmAdapter(transport=httpx.MockTransport(handler))
    request = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
    )

    with pytest.raises(RuntimeError, match="timed out"):
        async for _ in adapter.complete(request):
            pass
