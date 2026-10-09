"""vLLM thin model adapter implementation."""

import json
from collections.abc import AsyncIterator

import httpx

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import (
    CompletionRequest,
    StreamChunk,
    ThinkingLevel,
    estimate_tokens,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.openai_payload import build_payload
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore
from agent_os.infrastructure.gateway.tool_call_accumulator import ToolCallAccumulator


class VllmAdapter(BaseModelAdapter):
    """vLLM and OpenAI-compatible streaming model adapter using HTTP/SSE."""

    def __init__(
        self,
        config: AppConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        semaphore: InferenceSemaphore | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.transport = transport
        self.semaphore = semaphore

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion tokens from the model endpoint."""
        if self.semaphore:
            async with self.semaphore.acquire():
                async for chunk in self._stream_request(request):
                    yield chunk
        else:
            async for chunk in self._stream_request(request):
                yield chunk

    def _clamp_max_tokens(self, request: CompletionRequest) -> int:
        prompt_tokens = sum(estimate_tokens(msg.text) for msg in request.messages)
        available_output = max(128, self.config.vllm_context_window - prompt_tokens)
        clamped = min(request.max_tokens, available_output)
        # G1 headroom: ensure output headroom when reasoning is enabled
        is_thinking = request.thinking_level in (
            ThinkingLevel.LOW,
            ThinkingLevel.MEDIUM,
            ThinkingLevel.HIGH,
            ThinkingLevel.MAX,
        ) or (request.thinking_level is None and self.config.vllm_enable_thinking is not False)
        if is_thinking and clamped < 2048:
            clamped = min(2048, available_output)
        return clamped

    async def _stream_request(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.config.vllm_base_url.rstrip('/')}/chat/completions"
        payload = build_payload(request, self.config, self._clamp_max_tokens(request))
        headers = {
            "Authorization": f"Bearer {self.config.vllm_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.config.vllm_request_timeout,
            ) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise RuntimeError(
                            f"Model API returned HTTP {response.status_code}: "
                            f"{body.decode(errors='replace')}"
                        )
                    async for chunk in self._parse_sse(response):
                        yield chunk
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Model request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Model request failed: {exc}") from exc

    @staticmethod
    async def _parse_sse(response: httpx.Response) -> AsyncIterator[StreamChunk]:
        """Yield text/reasoning chunks; emit assembled tool calls once on the terminal chunk."""
        calls = ToolCallAccumulator()
        finished = False
        async for line in response.aiter_lines():
            stripped = line.strip()
            if not stripped.startswith("data:"):
                continue
            data_str = stripped[len("data:") :].strip()
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            calls.add(delta.get("tool_calls") or [])
            content = delta.get("content") or ""
            reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
            finish_reason = choice.get("finish_reason")
            if finish_reason is not None and not finished:
                finished = True
                yield StreamChunk(
                    delta=content,
                    reasoning=reasoning,
                    finish_reason=finish_reason,
                    tool_calls=calls.build(),
                )
            elif content or reasoning:
                yield StreamChunk(delta=content, reasoning=reasoning)
        if not finished and calls.has_calls:
            yield StreamChunk(delta="", finish_reason="tool_calls", tool_calls=calls.build())
