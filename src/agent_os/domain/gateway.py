"""Domain layer definitions for model gateway, canonical message parts, and completions."""

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class ThinkingLevel(StrEnum):
    """Normalized thinking ladder with graceful step-down."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"


class TextPart(BaseModel):
    """Plain natural language text content."""

    type: Literal["text"] = "text"
    text: str


class ThinkingPart(BaseModel):
    """Reasoning or chain-of-thought tokens with an opaque provider envelope."""

    type: Literal["thinking"] = "thinking"
    thought: str
    provider_data: dict[str, Any] = Field(default_factory=dict)


class ToolCallPart(BaseModel):
    """Structured invocation of a tool."""

    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    arguments: str


class ToolResultPart(BaseModel):
    """Execution observation returned from a tool."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    name: str
    output: str
    is_error: bool = False


class FileRefPart(BaseModel):
    """Local file or attachment pointer by path or hash (never raw data bloat)."""

    type: Literal["file_ref"] = "file_ref"
    path: str
    media_type: str = "application/octet-stream"
    description: str | None = None


MessagePart = Annotated[
    TextPart | ThinkingPart | ToolCallPart | ToolResultPart | FileRefPart,
    Field(discriminator="type"),
]


class ChatMessage(BaseModel):
    """Chat message schema supporting text and canonical message parts."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    parts: list[MessagePart] = Field(default_factory=list)
    name: str | None = None
    tool_call_id: str | None = None

    def model_post_init(self, __context: Any) -> None:
        """Ensure consistency between content string and parts list."""
        if self.content and not self.parts:
            self.parts.append(TextPart(text=self.content))
        elif self.parts and not self.content:
            text_chunks = [p.text for p in self.parts if isinstance(p, TextPart)]
            self.content = "".join(text_chunks)

    @property
    def text(self) -> str:
        """Extract all natural language text from message parts."""
        if self.content:
            return self.content
        text_chunks = [p.text for p in self.parts if isinstance(p, TextPart)]
        return "".join(text_chunks)


class CompletionRequest(BaseModel):
    """Model completion request schema."""

    role: str = "chat"
    thinking_level: ThinkingLevel | None = None
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    stream: bool = True


class StreamChunk(BaseModel):
    """Single streamed token or finish reason chunk."""

    delta: str
    finish_reason: str | None = None
    reasoning: str = ""
    provider_data: dict[str, Any] = Field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Estimate token count with conservative margin for code, symbols, and formatting."""
    if not text:
        return 0
    char_est = int(len(text) / 3.5)
    word_est = len(text.split())
    return max(1, max(char_est, word_est))

