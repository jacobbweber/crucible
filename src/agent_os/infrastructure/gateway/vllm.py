"""vLLM thin model adapter implementation."""

import json
from collections.abc import AsyncIterator

import httpx

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.infrastructure.gateway.base import BaseModelAdapter


class VllmAdapter(BaseModelAdapter):
    """vLLM streaming model adapter using HTTP/SSE."""

    def __init__(
        self,
        config: AppConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config or AppConfig()
        self.transport = transport

    async def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion tokens from the vLLM /chat/completions endpoint."""
        url = f"{self.config.vllm_base_url.rstrip('/')}/chat/completions"
        clamped_max_tokens = min(request.max_tokens, self.config.vllm_context_window)

        payload: dict[str, object] = {
            "model": request.model or self.config.vllm_model_name,
            "messages": [msg.model_dump(exclude_none=True) for msg in request.messages],
            "temperature": request.temperature,
            "max_tokens": clamped_max_tokens,
            "stream": True,
        }
        thinking = self.config.vllm_enable_thinking
        if thinking is not None:
            # vLLM chat templates read chat_template_kwargs; Ollama only honours reasoning_effort.
            payload["chat_template_kwargs"] = {"enable_thinking": thinking}
            if not thinking:
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
                            f"vLLM API returned HTTP {response.status_code}: {error_text}"
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
                            delta_dict.get("reasoning")
                            or delta_dict.get("reasoning_content")
                            or ""
                        )
                        finish_reason = first_choice.get("finish_reason")

                        if content or reasoning or finish_reason is not None:
                            yield StreamChunk(
                                delta=content,
                                finish_reason=finish_reason,
                                reasoning=reasoning,
                            )
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"vLLM request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise RuntimeError(f"vLLM request failed: {exc}") from exc
