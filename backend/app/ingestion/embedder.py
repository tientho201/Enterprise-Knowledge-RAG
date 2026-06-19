"""
OpenAI Embeddings — replaces BGE-M3 local model.
Uses text-embedding-3-small by default (1536 dims, cost-effective).
"""
from functools import lru_cache

from openai import OpenAI

from app.core.config import settings

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder:
    """Wraps OpenAI Embeddings API with batched calls."""

    def __init__(self, model: str = None, batch_size: int = None):
        self.model = model or settings.EMBEDDING_MODEL
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self._client = OpenAI(api_key=settings.OPENAI_API_KEY)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches, return vectors (already normalized by OpenAI)."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            response = self._client.embeddings.create(
                model=self.model,
                input=batch,
            )
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        return _DIMENSIONS.get(self.model, 1536)


@lru_cache
def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()
