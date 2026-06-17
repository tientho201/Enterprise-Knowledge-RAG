"""
Hybrid retrieval: Dense (Qdrant) + Sparse (BM25) with weighted merge.
Dense weight: 0.7, Sparse weight: 0.3
"""
from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import QdrantClient

from app.core.config import settings


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    chunk_index: int


@lru_cache
def get_qdrant_client() -> QdrantClient:
    """
    Tạo Qdrant client:
    - Nếu QDRANT_API_KEY được set → kết nối Qdrant Cloud qua QDRANT_URL
    - Ngược lại → kết nối local (development)
    """
    if settings.QDRANT_API_KEY:
        return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    return QdrantClient(url=settings.QDRANT_URL)


class HybridRetriever:
    """
    Combines dense (Qdrant cosine similarity) and sparse (BM25) retrieval.
    Scores are merged: final = dense_weight * dense_score + sparse_weight * bm25_score
    """

    def __init__(
        self,
        dense_top_k: int = None,
        sparse_top_k: int = None,
        dense_weight: float = None,
        sparse_weight: float = None,
    ):
        self.dense_top_k = dense_top_k or settings.DENSE_TOP_K
        self.sparse_top_k = sparse_top_k or settings.SPARSE_TOP_K
        self.dense_weight = dense_weight or settings.DENSE_WEIGHT
        self.sparse_weight = sparse_weight or settings.SPARSE_WEIGHT
        self._qdrant = get_qdrant_client()

    def _dense_search(self, query_embedding: list[float]) -> list[RetrievedChunk]:
        results = self._qdrant.search(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query_vector=query_embedding,
            limit=self.dense_top_k,
            with_payload=True,
        )
        return [
            RetrievedChunk(
                chunk_id=str(hit.id),
                document_id=hit.payload.get("document_id", ""),
                document_name=hit.payload.get("document_name", ""),
                content=hit.payload.get("content", ""),
                score=hit.score,
                chunk_index=hit.payload.get("chunk_index", 0),
            )
            for hit in results
        ]

    def _bm25_search(self, query: str, corpus: list[RetrievedChunk]) -> dict[str, float]:
        """BM25 re-scoring over dense results corpus."""
        if not corpus:
            return {}
        from rank_bm25 import BM25Okapi
        tokenized_corpus = [c.content.lower().split() for c in corpus]
        bm25 = BM25Okapi(tokenized_corpus)
        scores = bm25.get_scores(query.lower().split())
        max_score = max(scores) if max(scores) > 0 else 1.0
        return {corpus[i].chunk_id: scores[i] / max_score for i in range(len(corpus))}

    def retrieve(self, query: str, query_embedding: list[float]) -> list[RetrievedChunk]:
        dense_results = self._dense_search(query_embedding)
        if not dense_results:
            return []

        bm25_scores = self._bm25_search(query, dense_results)

        # Normalize dense scores to [0,1]
        max_dense = max(r.score for r in dense_results) or 1.0

        merged: dict[str, RetrievedChunk] = {}
        for chunk in dense_results:
            norm_dense = chunk.score / max_dense
            norm_bm25 = bm25_scores.get(chunk.chunk_id, 0.0)
            hybrid_score = self.dense_weight * norm_dense + self.sparse_weight * norm_bm25
            chunk.score = hybrid_score
            merged[chunk.chunk_id] = chunk

        return sorted(merged.values(), key=lambda x: x.score, reverse=True)
