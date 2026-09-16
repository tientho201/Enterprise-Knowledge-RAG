"""
Re-ranker: selects top-K from retrieval results.

STOPGAP IMPLEMENTATION: sorts by the hybrid score already computed by
HybridRetriever (dense + graph weighted merge) and truncates to top_k.
No model load, no extra dependency, no extra cost.

Trước đây dùng sentence-transformers CrossEncoder (cross-encoder/ms-marco-MiniLM-L-6-v2),
nhưng torch/sentence-transformers đã bị loại khỏi pyproject.toml (không dùng ở đâu khác,
~2.5GB image size). Class/interface giữ nguyên (`rerank()`, `get_reranker()`) nên
grader_node không cần đổi gì.

TODO: nếu cần chất lượng rerank tốt hơn hybrid score thô, cân nhắc:
  - Cohere Rerank API (rẻ, không cần tự host model)

(grader_node đã batch 1 LLM call chấm điểm tất cả chunks cùng lúc — xem grader.py,
không còn N calls như trước.)
"""

from functools import lru_cache

from app.core.config import settings
from app.rag.retriever import RetrievedChunk


class HybridScoreReranker:
    """Re-ranks retrieved chunks by their existing hybrid score (dense+graph)."""

    def __init__(self, top_k: int | None = None):
        self.top_k = top_k or settings.RERANK_TOP_K

    def rerank(
        self,
        query: str,  # noqa: ARG002
        chunks: list[RetrievedChunk],
        top_k: int | None = None,
    ) -> list[RetrievedChunk]:
        if not chunks:
            return []
        # top_k từ UI (nếu có) override RERANK_TOP_K cấu hình
        limit = top_k if top_k is not None else self.top_k
        reranked = sorted(chunks, key=lambda x: x.score, reverse=True)
        return reranked[:limit]


@lru_cache
def get_reranker() -> HybridScoreReranker:
    return HybridScoreReranker()
