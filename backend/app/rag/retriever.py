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
    Return a cached Qdrant client.
    - QDRANT_API_KEY set  → Qdrant Cloud via QDRANT_URL
    - otherwise          → local / self-hosted
    """
    if settings.QDRANT_API_KEY:
        return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY)
    return QdrantClient(url=settings.QDRANT_URL)


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

    # ── Dense ─────────────────────────────────────────────────────────────────

    def _dense_search(self, query_embedding: list[float]) -> list[RetrievedChunk]:
        import httpx
        headers = {"Content-Type": "application/json"}
        if settings.QDRANT_API_KEY:
            headers["api-key"] = settings.QDRANT_API_KEY
            
        url = f"{settings.QDRANT_URL.rstrip('/')}/collections/{settings.QDRANT_COLLECTION_NAME}/points/search"
        payload = {
            "vector": query_embedding,
            "limit": self.dense_top_k,
            "with_payload": True,
            "with_vector": False
        }
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload, headers=headers)
                if response.status_code != 200:
                    import logging
                    logging.getLogger(__name__).error(
                        f"Qdrant search failed: status {response.status_code}, response {response.text}"
                    )
                    return []
                results = response.json().get("result", [])
                return [
                    RetrievedChunk(
                        chunk_id=str(hit["id"]),
                        document_id=hit.get("payload", {}).get("document_id", "") if hit.get("payload") else "",
                        document_name=hit.get("payload", {}).get("document_name", "") if hit.get("payload") else "",
                        content=hit.get("payload", {}).get("content", "") if hit.get("payload") else "",
                        score=hit.get("score", 0.0),
                        chunk_index=hit.get("payload", {}).get("chunk_index", 0) if hit.get("payload") else 0,
                    )
                    for hit in results
                ]
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Error calling Qdrant search REST API")
            return []

    # ── Graph ─────────────────────────────────────────────────────────────────

    def _graph_search(
        self, seed_ids: list[str]
    ) -> dict[str, tuple[RetrievedChunk, float]]:
        """
        Expand seed chunks through the Neo4j knowledge graph.

        Cypher traversal (depth ≤ 2) follows NEXT_CHUNK and REFERENCES edges
        and returns chunks *not* already in the dense seed set.

        Returns: {chunk_id: (RetrievedChunk, normalized_score)}
        Graph score = connection_count / max_connection_count  ∈ [0, 1]

        Falls back to {} on any Neo4j error (connection refused, timeout, etc.).
        """
        if not seed_ids:
            return {}

        try:
            from app.rag.graph_client import get_neo4j_driver

            driver = get_neo4j_driver()
            with driver.session() as session:
                result = session.run(
                    """
                    UNWIND $seed_ids AS sid
                    MATCH (seed:Chunk {chunk_id: sid})
                    MATCH (seed)-[:NEXT_CHUNK|REFERENCES*1..2]-(related:Chunk)
                    WHERE NOT related.chunk_id IN $seed_ids
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
            return {}

    # ── Merge & rank ──────────────────────────────────────────────────────────

    def retrieve(self, query: str, query_embedding: list[float]) -> list[RetrievedChunk]:
        """
        Run hybrid retrieval and return chunks sorted by descending hybrid score.

        Args:
            query:           Raw user query string (unused post-dense but kept for
                             compatibility with future sparse/keyword augmentation).
            query_embedding: Pre-computed dense embedding of the query.
        """
        dense_results = self._dense_search(query_embedding)
        if not dense_results:
            return []

        seed_ids = [r.chunk_id for r in dense_results]
        graph_results = self._graph_search(seed_ids)

        max_dense = max(r.score for r in dense_results) or 1.0

        merged: dict[str, RetrievedChunk] = {}

        # Score dense results with optional graph boost
        for chunk in dense_results:
            norm_dense = chunk.score / max_dense
            _, graph_score = graph_results.get(chunk.chunk_id, (None, 0.0))
            chunk.score = self.dense_weight * norm_dense + self.graph_weight * graph_score
            merged[chunk.chunk_id] = chunk

        # Add graph-only chunks (not returned by dense search)
        for chunk_id, (chunk, graph_score) in graph_results.items():
            if chunk_id not in merged:
                chunk.score = self.graph_weight * graph_score
                merged[chunk_id] = chunk

        return sorted(merged.values(), key=lambda x: x.score, reverse=True)
