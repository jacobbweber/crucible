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
    assert captured_payload["max_tokens"] == 2047


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


@pytest.mark.asyncio
async def test_vllm_adapter_separates_reasoning_and_sends_thinking_toggle() -> None:
    """Verify reasoning deltas stay out of content and enable_thinking is forwarded."""
    captured: dict[str, Any] = {}
    sse_data = (
        'data: {"choices": [{"delta": {"reasoning": "Let me think"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "Hi"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, text=sse_data)

    adapter = VllmAdapter(
        config=AppConfig(vllm_enable_thinking=False), transport=httpx.MockTransport(handler)
    )
    request = CompletionRequest(messages=[ChatMessage(role="user", content="Hi")])
    chunks = [c async for c in adapter.complete(request)]

    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["reasoning_effort"] == "none"
    assert "".join(c.delta for c in chunks) == "Hi"
    assert "".join(c.reasoning for c in chunks) == "Let me think"


@pytest.mark.asyncio
async def test_vllm_adapter_thinking_level_ladder() -> None:
    """Verify ThinkingLevel.LOW and NONE are mapped properly into request payload."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, text="data: [DONE]\n\n")

    adapter = VllmAdapter(transport=httpx.MockTransport(handler))

    from agent_os.domain.gateway import ThinkingLevel

    # Test ThinkingLevel.LOW
    req_low = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        thinking_level=ThinkingLevel.LOW,
    )
    _ = [c async for c in adapter.complete(req_low)]
    assert captured["chat_template_kwargs"] == {"enable_thinking": True}
    assert captured["reasoning_effort"] == "low"

    # Test ThinkingLevel.NONE
    req_none = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        thinking_level=ThinkingLevel.NONE,
    )
    _ = [c async for c in adapter.complete(req_none)]
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_vllm_adapter_semaphore_concurrency_gating() -> None:
    """Verify complete() acquires the shared InferenceSemaphore during execution."""
    from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore

    semaphore = InferenceSemaphore(max_concurrency=1)
    entered_sem = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal entered_sem
        entered_sem = semaphore.active_workers == 1
        return httpx.Response(200, text="data: [DONE]\n\n")

    adapter = VllmAdapter(semaphore=semaphore, transport=httpx.MockTransport(handler))
    req = CompletionRequest(messages=[ChatMessage(role="user", content="Hi")])
    _ = [c async for c in adapter.complete(req)]
    assert entered_sem is True
    assert semaphore.active_workers == 0


@pytest.mark.asyncio
async def test_vllm_adapter_normalizes_tool_message_id() -> None:
    """Verify tool role messages receive a tool_call_id to satisfy OpenAI endpoints (H3)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, text="data: [DONE]\n\n")

    adapter = VllmAdapter(transport=httpx.MockTransport(handler))
    tool_msg = ChatMessage(role="tool", content="obs", name="wiki_read")
    req = CompletionRequest(messages=[tool_msg])
    _ = [c async for c in adapter.complete(req)]

    assert captured["messages"][0]["tool_call_id"] == "call_wiki_read"


@pytest.mark.asyncio
async def test_vllm_adapter_reserves_thinking_headroom() -> None:
    """Verify max_tokens expands to at least 2048 when thinking is active (G1)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, text="data: [DONE]\n\n")

    from agent_os.domain.gateway import ThinkingLevel

    adapter = VllmAdapter(
        config=AppConfig(vllm_context_window=4096),
        transport=httpx.MockTransport(handler),
    )
    req = CompletionRequest(
        messages=[ChatMessage(role="user", content="Hi")],
        thinking_level=ThinkingLevel.HIGH,
        max_tokens=64,  # Intentionally small
    )
    _ = [c async for c in adapter.complete(req)]
    assert captured["max_tokens"] == 2048
