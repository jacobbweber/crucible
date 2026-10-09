"""Model adapter decorator that mirrors every request and streamed response to a trace sink."""

from collections.abc import AsyncIterator, Callable

from agent_os.domain.gateway import CompletionRequest, StreamChunk
from agent_os.infrastructure.gateway.base import BaseModelAdapter

TraceSink = Callable[[str, str], None]
"""Callable receiving (event_kind, text). Kinds: request, reasoning, delta, tool_call, end."""


class TracingModelAdapter(BaseModelAdapter):
    """Wraps another adapter and reports traffic to a sink while tracing is enabled."""

    def __init__(self, inner: BaseModelAdapter, sink: TraceSink, enabled: bool = False) -> None:
        self.inner = inner
        self.sink = sink
        self.enabled = enabled
        self.call_count = 0

    def _render_request(self, request: CompletionRequest) -> str:
        lines = [f"model={request.model or 'default'} temp={request.temperature}"]
        if request.tools:
            names = ", ".join(t.name for t in request.tools)
            lines.append(f"tools=[{names}] tool_choice={request.tool_choice}")
        if request.response_schema is not None:
            lines.append(f"response_schema={request.response_schema.name}")
        for msg in request.messages:
            lines.append(f"[{msg.role}{':' + msg.name if msg.name else ''}]\n{msg.content}")
        return "\n".join(lines)

    async def complete(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Delegate to the inner adapter, echoing traffic to the sink when enabled."""
        self.call_count += 1
        if self.enabled:
            self.sink("request", f"#{self.call_count} " + self._render_request(request))
        finish: str | None = None
        async for chunk in self.inner.complete(request):
            if self.enabled:
                if chunk.reasoning:
                    self.sink("reasoning", chunk.reasoning)
                if chunk.delta:
                    self.sink("delta", chunk.delta)
                for call in chunk.tool_calls:
                    self.sink("tool_call", f"{call.name}({call.arguments})")
            finish = chunk.finish_reason or finish
            yield chunk
        if self.enabled:
            self.sink("end", f"#{self.call_count} finish_reason={finish}")
