"""vLLM thin model adapter implementation."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import (
    CompletionRequest,
    StreamChunk,
    ThinkingLevel,
    estimate_tokens,
)
from agent_os.infrastructure.gateway.base import BaseModelAdapter
from agent_os.infrastructure.gateway.semaphore import InferenceSemaphore


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

    async def _stream_request(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        url = f"{self.config.vllm_base_url.rstrip('/')}/chat/completions"
        prompt_tokens = sum(estimate_tokens(msg.text) for msg in request.messages)
        available_output = max(128, self.config.vllm_context_window - prompt_tokens)
        clamped_max_tokens = min(request.max_tokens, available_output)

        # G1 headroom: ensure output headroom when reasoning is enabled
        is_thinking = request.thinking_level in (
            ThinkingLevel.LOW,
            ThinkingLevel.MEDIUM,
            ThinkingLevel.HIGH,
            ThinkingLevel.MAX,
        ) or (request.thinking_level is None and self.config.vllm_enable_thinking is not False)
        if is_thinking and clamped_max_tokens < 2048:
            clamped_max_tokens = min(2048, available_output)

        # Format messages and resolve H3 (tool messages require tool_call_id)
        formatted_messages: list[dict[str, Any]] = []
        for msg in request.messages:
            item: dict[str, Any] = {"role": msg.role, "content": msg.text}
            if msg.name:
                item["name"] = msg.name
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            elif msg.role == "tool":
                item["tool_call_id"] = f"call_{msg.name or 'default'}"
            formatted_messages.append(item)

        payload: dict[str, Any] = {
            "model": request.model or self.config.vllm_model_name,
            "messages": formatted_messages,
            "temperature": request.temperature,
            "max_tokens": clamped_max_tokens,
            "stream": True,
        }

        # Apply normalized thinking ladder
        level = request.thinking_level
        if level == ThinkingLevel.NONE:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
            payload["reasoning_effort"] = "none"
        elif level is not None:
            effort_map: dict[ThinkingLevel, str] = {
                ThinkingLevel.LOW: "low",
                ThinkingLevel.MEDIUM: "medium",
                ThinkingLevel.HIGH: "high",
                ThinkingLevel.MAX: "high",
            }
            payload["chat_template_kwargs"] = {"enable_thinking": True}
            payload["reasoning_effort"] = effort_map.get(level, "high")
        elif self.config.vllm_enable_thinking is not None:
            payload["chat_template_kwargs"] = {"enable_thinking": self.config.vllm_enable_thinking}
            if not self.config.vllm_enable_thinking:
                payload["reasoning_effort"] = "none"

        headers = {
            "Authorization": f"Bearer {self.config.vllm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.config.vllm_request_timeout,
            ) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        error_text = body.decode(errors="replace")
                        raise RuntimeError(
                            f"Model API returned HTTP {response.status_code}: {error_text}"
                        )

                    async for line in response.aiter_lines():
                        stripped = line.strip()
                        if not stripped or not stripped.startswith("data:"):
                            continue

                        data_str = stripped[len("data:") :].strip()
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        first_choice = choices[0]
                        delta_dict = first_choice.get("delta", {})
                        content = delta_dict.get("content", "") or ""
                        reasoning = (
                            delta_dict.get("reasoning") or delta_dict.get("reasoning_content") or ""
                        )
                        finish_reason = first_choice.get("finish_reason")

                        if content or reasoning or finish_reason is not None:
                            yield StreamChunk(
                                delta=content,
                                finish_reason=finish_reason,
                                reasoning=reasoning,
                            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"Model request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"Model request failed: {exc}") from exc
