"""Domain layer definitions for model gateway and chat completions."""

from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Chat message schema."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None


class CompletionRequest(BaseModel):
    """Model completion request schema."""

    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)
    stream: bool = True


class StreamChunk(BaseModel):
    """Single streamed token or finish reason chunk."""

    delta: str
    finish_reason: str | None = None
