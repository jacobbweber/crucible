"""Translate canonical CompletionRequests into OpenAI-compatible chat payloads."""

from typing import Any

from agent_os.domain.config import AppConfig
from agent_os.domain.gateway import ChatMessage, CompletionRequest, ThinkingLevel

_EFFORT: dict[ThinkingLevel, str] = {
    ThinkingLevel.LOW: "low",
    ThinkingLevel.MEDIUM: "medium",
    ThinkingLevel.HIGH: "high",
    ThinkingLevel.MAX: "high",
}


def format_message(msg: ChatMessage) -> dict[str, Any]:
    """Render one canonical message, including assistant tool calls and tool results."""
    item: dict[str, Any] = {"role": msg.role, "content": msg.text}
    if msg.name:
        item["name"] = msg.name
    calls = msg.tool_calls
    if msg.role == "assistant" and calls:
        item["content"] = msg.text or None
        item["tool_calls"] = [
            {
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.arguments},
            }
            for c in calls
        ]
    if msg.tool_call_id:
        item["tool_call_id"] = msg.tool_call_id
    elif msg.role == "tool":
        item["tool_call_id"] = f"call_{msg.name or 'default'}"
    return item


def _thinking_fields(request: CompletionRequest, config: AppConfig) -> dict[str, Any]:
    level = request.thinking_level
    if level == ThinkingLevel.NONE:
        return {"chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"}
    if level is not None:
        return {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_effort": _EFFORT.get(level, "high"),
        }
    if config.vllm_enable_thinking is None:
        return {}
    fields: dict[str, Any] = {
        "chat_template_kwargs": {"enable_thinking": config.vllm_enable_thinking}
    }
    if not config.vllm_enable_thinking:
        fields["reasoning_effort"] = "none"
    return fields


def _structured_fields(request: CompletionRequest) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if request.tools:
        fields["tools"] = [{"type": "function", "function": t.model_dump()} for t in request.tools]
        if request.tool_choice in ("auto", "none"):
            fields["tool_choice"] = request.tool_choice
        else:
            fields["tool_choice"] = {
                "type": "function",
                "function": {"name": request.tool_choice},
            }
    if request.response_schema is not None:
        rs = request.response_schema
        fields["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": rs.name, "schema": rs.schema_, "strict": rs.strict},
        }
    return fields


def build_payload(request: CompletionRequest, config: AppConfig, max_tokens: int) -> dict[str, Any]:
    """Assemble the full streaming chat-completions payload."""
    return {
        "model": request.model or config.vllm_model_name,
        "messages": [format_message(m) for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": max_tokens,
        "stream": True,
        **_thinking_fields(request, config),
        **_structured_fields(request),
    }
