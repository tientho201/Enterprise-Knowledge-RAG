from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BaseLLM(ABC):
    """Abstract base class for all LLM implementations."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request and return the response text."""

    @abstractmethod
    def stream_chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Stream a chat completion response."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return their vectors."""
