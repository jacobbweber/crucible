"""Abstract base model adapter interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from agent_os.domain.gateway import CompletionRequest, StreamChunk


class BaseModelAdapter(ABC):
    """Abstract base class for all model adapters."""

    @abstractmethod
    def complete(
        self,
        request: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Stream completion tokens for a given request."""
        ...
