"""
Hybrid retrieval: Dense (Qdrant) + Graph (Neo4j) with weighted merge.

Dense weight : 0.7  — cosine similarity from Qdrant vector search
Graph weight : 0.3  — knowledge-graph expansion via Neo4j

Graph search starts from the dense seed chunks and expands through:
  • NEXT_CHUNK  — adjacent chunks in the same document (context window)
  • REFERENCES  — chunks that are cross-referenced by a seed chunk's text
                  (e.g. "theo quy định tại Điều 5")

Graceful degradation: if Neo4j is unavailable the pipeline falls back to
dense-only mode without raising an exception.
"""

import logging
from dataclasses import dataclass, replace
from functools import lru_cache

from qdrant_client import QdrantClient

from app.core.config import settings

logger = logging.getLogger(__name__)


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
    Return a cached Qdrant client.
    - QDRANT_API_KEY set  → Qdrant Cloud via QDRANT_URL
    - otherwise          → local / self-hosted
    """
    # timeout rộng: Qdrant Cloud có thể ở region xa (vd sa-east-1) → độ trễ cao;
    # upsert/ delete theo batch vẫn cần đủ thời gian, tránh "write operation timed out".
    if settings.QDRANT_API_KEY:
        return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)
    return QdrantClient(url=settings.QDRANT_URL, timeout=60)


class HybridRetriever:
    """
    Two-stage retrieval:

    1. Dense  — Qdrant ANN search returns top-K semantically similar chunks.
    2. Graph  — Neo4j BFS from the dense seeds expands the result set with
                contextually related chunks (next/prev chunks, referenced articles).

    Final score = dense_weight * norm_dense + graph_weight * graph_score
    """

    def __init__(
        self,
        dense_top_k: int | None = None,
        graph_top_k: int | None = None,
        dense_weight: float | None = None,
        graph_weight: float | None = None,
    ):
        self.dense_top_k = dense_top_k or settings.DENSE_TOP_K
        self.graph_top_k = graph_top_k or settings.GRAPH_TOP_K
        self.dense_weight = dense_weight or settings.DENSE_WEIGHT
        self.graph_weight = graph_weight or settings.GRAPH_WEIGHT
        self._qdrant = get_qdrant_client()

    # ── Filter helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _build_qdrant_filter(
        document_ids: list[str] | None,
        owner_id: str | None,
        *,
        excluded_document_ids: list[str] | None = None,
    ) -> dict | None:
        """
        Build a Qdrant payload filter combining optional document scoping,
        owner-based data isolation and document exclusion.

        owner_id=None  → không filter theo owner (admin: truy hồi mọi chunk).
        owner_id=<id>  → chỉ chunk của doc thuộc user đó. Chunk legacy (ingest
                         trước khi có owner_id trong payload) không có field này
                         nên bị loại — nhất quán với list_documents ẩn doc owner=NULL.

        excluded_document_ids (vd: tài liệu đang tắt) → thêm khối `must_not`.
        Loại trừ chỉ THU HẸP kết quả: nó được AND với `must`, không bao giờ thay
        thế hay nới lỏng điều kiện owner_id; doc vừa nằm trong document_ids vừa
        nằm trong excluded thì vẫn bị loại. None/rỗng → filter y hệt như trước.
        """
        must: list[dict] = []
        if document_ids:
            must.append({"key": "document_id", "match": {"any": document_ids}})
        if owner_id is not None:
            must.append({"key": "owner_id", "match": {"value": owner_id}})

        qdrant_filter: dict = {}
        if must:
            qdrant_filter["must"] = must
        if excluded_document_ids:
            qdrant_filter["must_not"] = [
                {"key": "document_id", "match": {"any": list(excluded_document_ids)}}
            ]
        return qdrant_filter or None

    # ── Dense ─────────────────────────────────────────────────────────────────

    def _dense_search(
        self,
        query_embedding: list[float],
        document_ids: list[str] | None = None,
        owner_id: str | None = None,
        score_threshold: float | None = None,
        *,
        excluded_document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if settings.QDRANT_API_KEY:
            headers["api-key"] = settings.QDRANT_API_KEY

        url = f"{settings.QDRANT_URL.rstrip('/')}/collections/{settings.QDRANT_COLLECTION_NAME}/points/search"
        payload: dict = {
            "vector": query_embedding,
            "limit": self.dense_top_k,
            "with_payload": True,
            "with_vector": False,
        }
        # Ngưỡng tương đồng từ UI: Qdrant chỉ trả điểm cosine >= threshold.
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        qdrant_filter = self._build_qdrant_filter(
            document_ids, owner_id, excluded_document_ids=excluded_document_ids
        )
        if qdrant_filter:
            payload["filter"] = qdrant_filter
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    logger.error(
                        f"Qdrant search failed: status {response.status_code}, response {response.text}"
                    )
                    return []
                results = response.json().get("result", [])
                return [
                    RetrievedChunk(
                        chunk_id=str(hit["id"]),
                        document_id=hit.get("payload", {}).get("document_id", "")
                        if hit.get("payload")
                        else "",
                        document_name=hit.get("payload", {}).get("document_name", "")
                        if hit.get("payload")
                        else "",
                        content=hit.get("payload", {}).get("content", "")
                        if hit.get("payload")
                        else "",
                        score=hit.get("score", 0.0),
                        chunk_index=hit.get("payload", {}).get("chunk_index", 0)
                        if hit.get("payload")
                        else 0,
                    )
                    for hit in results
                ]
        except Exception:
            logger.exception("Error calling Qdrant search REST API")
            return []

    # ── Graph ─────────────────────────────────────────────────────────────────

    def _graph_search(
        self,
        seed_ids: list[str],
        document_ids: list[str] | None = None,
        owner_id: str | None = None,
        *,
        excluded_document_ids: list[str] | None = None,
    ) -> dict[str, tuple[RetrievedChunk, float]]:
        """
        Expand seed chunks through the Neo4j knowledge graph.

        Cypher traversal (depth ≤ 2) follows NEXT_CHUNK and REFERENCES edges
        and returns chunks *not* already in the dense seed set.

        Data isolation: seeds đã owner-scoped từ dense search, nhưng REFERENCES
        có thể trỏ sang doc khác → filter thêm `related.owner_id = $owner_id` để
        graph expansion không chạm chunk của người khác. owner_id=None (admin)
        bỏ qua filter này.

        Loại trừ tài liệu: seeds đã bỏ doc bị loại ở dense search, nhưng
        NEXT_CHUNK/REFERENCES vẫn có thể dẫn sang chunk của doc bị loại (vd doc
        đang tắt) → thêm `NOT related.document_id IN $excluded_document_ids`.
        Điều kiện này được AND thêm vào, áp dụng cho cả admin, và không thay
        đổi owner filter. None/rỗng → câu Cypher y hệt như trước.

        Returns: {chunk_id: (RetrievedChunk, normalized_score)}
        Graph score = connection_count / max_connection_count  ∈ [0, 1]

        Falls back to {} on any Neo4j error (connection refused, timeout, etc.).
        Lỗi được ghi WARNING kèm traceback để việc rơi về dense-only không còn
        im lặng. Bản ghi chỉ chứa số lượng và owner_id — KHÔNG ghi nội dung
        chunk hay câu hỏi (PII).
        """
        if not seed_ids:
            return {}

        try:
            from app.rag.graph_client import get_neo4j_driver

            doc_filter = ""
            if document_ids:
                doc_filter = "AND related.document_id IN $document_ids"

            owner_filter = ""
            if owner_id is not None:
                owner_filter = "AND related.owner_id = $owner_id"

            excluded_filter = ""
            if excluded_document_ids:
                excluded_filter = "AND NOT related.document_id IN $excluded_document_ids"

            driver = get_neo4j_driver()
            with driver.session() as session:
                result = session.run(
                    f"""
                    UNWIND $seed_ids AS sid
                    MATCH (seed:Chunk {{chunk_id: sid}})
                    MATCH (seed)-[:NEXT_CHUNK|REFERENCES*1..2]-(related:Chunk)
                    WHERE NOT related.chunk_id IN $seed_ids
                    {doc_filter}
                    {owner_filter}
                    {excluded_filter}
                    RETURN
                        related.chunk_id       AS chunk_id,
                        related.document_id    AS document_id,
                        related.document_name  AS document_name,
                        related.content        AS content,
                        related.chunk_index    AS chunk_index,
                        count(seed)            AS connections
                    ORDER BY connections DESC
                    LIMIT $limit
                    """,
                    seed_ids=seed_ids,
                    document_ids=document_ids,
                    owner_id=owner_id,
                    excluded_document_ids=list(excluded_document_ids or []),
                    limit=self.graph_top_k,
                )
                records = result.data()

            if not records:
                return {}

            max_conn = max(r["connections"] for r in records) or 1
            graph_results: dict[str, tuple[RetrievedChunk, float]] = {}
            for r in records:
                norm_score = r["connections"] / max_conn
                chunk = RetrievedChunk(
                    chunk_id=r["chunk_id"],
                    document_id=r["document_id"],
                    document_name=r["document_name"],
                    content=r["content"],
                    score=norm_score,
                    chunk_index=r["chunk_index"],
                )
                graph_results[r["chunk_id"]] = (chunk, norm_score)

            return graph_results

        except Exception:  # Neo4j unavailable → graceful degradation
            # Chỉ log số đếm + owner_id; không log seed_ids, nội dung chunk hay câu hỏi.
            logger.warning(
                "Neo4j graph search failed, falling back to dense-only "
                "(seed_count=%d, owner_id=%s, excluded_count=%d)",
                len(seed_ids),
                owner_id,
                len(excluded_document_ids or []),
                exc_info=True,
            )
            return {}

    # ── Merge & rank ──────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        document_ids: list[str] | None = None,
        owner_id: str | None = None,
        score_threshold: float | None = None,
        *,
        excluded_document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        Run hybrid retrieval and return chunks sorted by descending hybrid score.

        Args:
            query:           Raw user query string (unused post-dense but kept for
                             compatibility with future sparse/keyword augmentation).
            query_embedding: Pre-computed dense embedding of the query.
            document_ids:    Optional user-supplied document scoping.
            owner_id:        Data-isolation boundary — chỉ truy hồi chunk của user này.
                             None = admin/không filter.
            excluded_document_ids:
                             Tài liệu phải loại khỏi kết quả (vd đang tắt). Áp dụng
                             cho CẢ nhánh dense lẫn nhánh graph, kể cả với admin.
                             None/rỗng = không loại gì (hành vi cũ).
        """
        dense_results = self._dense_search(
            query_embedding,
            document_ids,
            owner_id,
            score_threshold,
            excluded_document_ids=excluded_document_ids,
        )
        if not dense_results:
            return []

        seed_ids = [r.chunk_id for r in dense_results]
        graph_results = self._graph_search(
            seed_ids, document_ids, owner_id, excluded_document_ids=excluded_document_ids
        )

        return self.merge(dense_results, graph_results, excluded_document_ids=excluded_document_ids)

    def merge(
        self,
        dense_results: list[RetrievedChunk],
        graph_results: dict[str, tuple[RetrievedChunk, float]],
        *,
        excluded_document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        """
        Trộn điểm dense + graph thành danh sách xếp theo điểm hybrid giảm dần.

        Hàm THUẦN: không gọi mạng (Qdrant/Neo4j), không await, không đọc/ghi gì
        ngoài `self.dense_weight` / `self.graph_weight`. KHÔNG sửa tại chỗ đầu
        vào: mỗi chunk trả về là bản sao (`dataclasses.replace`), nên
        `dense_results` / `graph_results` của người gọi giữ nguyên điểm thô và
        gọi lại `merge()` trên cùng đầu vào luôn cho cùng kết quả.

        Args:
            dense_results: Kết quả `_dense_search` (điểm cosine thô của Qdrant).
            graph_results: Kết quả `_graph_search` —
                           {chunk_id: (RetrievedChunk, graph_score ∈ [0, 1])}.
            excluded_document_ids:
                           Tài liệu phải loại khỏi kết quả (vd đang tắt). Đây là
                           chốt chặn cuối của retriever và nằm NGAY TRONG hàm này:
                           ai gọi `merge()` trực tiếp (không qua `retrieve()`) PHẢI
                           truyền cùng danh sách đã đưa cho `_dense_search` /
                           `_graph_search`, nếu không chốt chặn bị bỏ qua.
                           None/rỗng = không loại gì.

        Điểm:
            chunk có ở dense : dense_weight * (score / max_dense)
                               + graph_weight * graph_score (0.0 nếu không có ở graph)
            chunk chỉ ở graph: graph_weight * graph_score
        `max_dense` = điểm dense lớn nhất, tính trên TOÀN BỘ `dense_results` (kể
        cả chunk sau đó bị loại trừ); bằng 0 thì dùng 1.0 để không chia cho 0.

        `dense_results` rỗng → [] (không có seed thì không có gì để trộn, kể cả
        khi `graph_results` khác rỗng) — đúng như `retrieve()` trước giờ.
        Điểm bằng nhau giữ thứ tự: dense trước (theo thứ tự đầu vào), rồi tới
        chunk chỉ-có-ở-graph (theo thứ tự của dict).
        """
        if not dense_results:
            return []

        max_dense = max(r.score for r in dense_results) or 1.0

        merged: dict[str, RetrievedChunk] = {}

        # Score dense results with optional graph boost
        for chunk in dense_results:
            norm_dense = chunk.score / max_dense
            _, graph_score = graph_results.get(chunk.chunk_id, (None, 0.0))
            merged[chunk.chunk_id] = replace(
                chunk, score=self.dense_weight * norm_dense + self.graph_weight * graph_score
            )

        # Add graph-only chunks (not returned by dense search)
        for chunk_id, (chunk, graph_score) in graph_results.items():
            if chunk_id not in merged:
                merged[chunk_id] = replace(chunk, score=self.graph_weight * graph_score)

        # Chốt chặn cuối: dù filter ở Qdrant/Neo4j có sót (payload thiếu field,
        # dữ liệu graph lệch), chunk của doc bị loại không được rời khỏi retriever.
        if excluded_document_ids:
            excluded = set(excluded_document_ids)
            for chunk_id in [cid for cid, c in merged.items() if c.document_id in excluded]:
                del merged[chunk_id]

        return sorted(merged.values(), key=lambda x: x.score, reverse=True)
