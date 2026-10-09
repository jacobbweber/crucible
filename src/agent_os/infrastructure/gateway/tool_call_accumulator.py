"""Assemble streamed tool-call fragments into complete canonical tool calls.

Providers differ: vLLM streams arguments as fragments keyed by `index`, while Ollama
emits each call whole in a single delta. Both shapes reduce to the same result here.
"""

from dataclasses import dataclass, field
from typing import Any

from agent_os.domain.gateway import ToolCallPart


@dataclass
class _PendingCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)


class ToolCallAccumulator:
    """Collects tool-call deltas across a stream and builds finished ToolCallParts."""

    def __init__(self) -> None:
        self._calls: list[_PendingCall] = []
        self._by_index: dict[int, _PendingCall] = {}

    def add(self, deltas: list[dict[str, Any]]) -> None:
        """Merge one SSE chunk's `delta.tool_calls` list."""
        for position, raw in enumerate(deltas):
            index = int(raw.get("index", position))
            call_id = str(raw.get("id") or "")
            pending = self._by_index.get(index)
            if pending is None or (call_id and pending.id and call_id != pending.id):
                pending = _PendingCall()
                self._by_index[index] = pending
                self._calls.append(pending)
            if call_id:
                pending.id = call_id
            fn = raw.get("function") or {}
            if fn.get("name"):
                pending.name = str(fn["name"])
            if fn.get("arguments"):
                pending.arguments.append(str(fn["arguments"]))

    @property
    def has_calls(self) -> bool:
        return bool(self._calls)

    def build(self) -> list[ToolCallPart]:
        """Return completed calls; unnamed fragments are dropped as malformed."""
        return [
            ToolCallPart(
                id=c.id or f"call_{i}",
                name=c.name,
                arguments="".join(c.arguments) or "{}",
            )
            for i, c in enumerate(self._calls)
            if c.name
        ]
