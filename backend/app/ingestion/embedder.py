"""
BGE-M3 local embedder — runs on CPU/GPU, normalized output.
Uses FlagEmbedding for dense + sparse embeddings.
"""
from functools import lru_cache

from app.core.config import settings


class BGEEmbedder:
    """Wraps FlagEmbedding BGEM3FlagModel for batch normalized embeddings."""

    def __init__(self, model_name: str = None, device: str = None, batch_size: int = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.device = device or settings.EMBEDDING_DEVICE
        self.batch_size = batch_size or settings.EMBEDDING_BATCH_SIZE
        self._model = None

    def _load_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel
            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=(self.device != "cpu"),
            )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches, return normalized dense vectors."""
        model = self._load_model()
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            output = model.encode(
                batch,
                batch_size=len(batch),
                max_length=512,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense = output["dense_vecs"]
            # Normalize
            import numpy as np
            norms = np.linalg.norm(dense, axis=1, keepdims=True)
            normalized = (dense / norms).tolist()
            all_embeddings.extend(normalized)

        return all_embeddings

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @property
    def dimension(self) -> int:
        """BGE-M3 dense embedding dimension."""
        return 1024


@lru_cache
def get_embedder() -> BGEEmbedder:
    return BGEEmbedder()
