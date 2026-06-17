"""
Cross-encoder re-ranker: selects top-K from retrieval results.
Uses sentence-transformers cross-encoder for relevance scoring.
"""
from functools import lru_cache

from app.core.config import settings
from app.rag.retriever import RetrievedChunk


class CrossEncoderReranker:
    """Re-ranks retrieved chunks using a cross-encoder model."""

    CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self, top_k: int = None):
        self.top_k = top_k or settings.RERANK_TOP_K
        self._model = None

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.CROSS_ENCODER_MODEL)
        return self._model

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not chunks:
            return []

        model = self._load_model()
        pairs = [(query, chunk.content) for chunk in chunks]
        scores = model.predict(pairs)

        for chunk, score in zip(chunks, scores):
            chunk.score = float(score)

        reranked = sorted(chunks, key=lambda x: x.score, reverse=True)
        return reranked[: self.top_k]


@lru_cache
def get_reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker()
