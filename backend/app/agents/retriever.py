"""
Retriever node: runs hybrid (dense + graph) search and populates state.

dense_results  — raw Qdrant ANN hits
graph_results  — Neo4j-expanded chunks (NEXT_CHUNK / REFERENCES traversal)
merged_results — hybrid-scored union, sorted by descending score
"""

import asyncio

from app.agents.state import AgentState
from app.ingestion.embedder import get_embedder
from app.rag.retriever import HybridRetriever


async def retriever_node(state: AgentState) -> AgentState:
    query = state.get("rewritten_query") or state["query"]

    embedder = get_embedder()
    retriever = HybridRetriever()

    # embedder.embed_query (sync OpenAI client), _dense_search (sync httpx.Client)
    # và _graph_search (sync Neo4j driver) đều block trên I/O mạng. Chạy qua
    # asyncio.to_thread để không giữ event loop FastAPI trong lúc chờ — nếu không,
    # mỗi query ở đây sẽ treo mọi request đồng thời khác cho tới khi xong.
    query_embedding = await asyncio.to_thread(embedder.embed_query, query)

    document_ids = state.get("document_ids")
    owner_id = state.get("owner_id")  # data isolation: None = admin/không filter
    score_threshold = state.get("similarity_threshold")  # ngưỡng tương đồng từ UI

    # Dense seeds (Qdrant)
    dense_results = await asyncio.to_thread(
        retriever._dense_search,
        query_embedding,
        document_ids=document_ids,
        owner_id=owner_id,
        score_threshold=score_threshold,
    )

    # Graph expansion (Neo4j) — returns {} if Neo4j is unavailable
    seed_ids = [r.chunk_id for r in dense_results]
    graph_map = await asyncio.to_thread(
        retriever._graph_search, seed_ids, document_ids=document_ids, owner_id=owner_id
    )
    graph_results = [chunk for chunk, _ in graph_map.values()]

    # Merge + hybrid score
    merged_results = await asyncio.to_thread(
        retriever.retrieve,
        query,
        query_embedding,
        document_ids=document_ids,
        owner_id=owner_id,
        score_threshold=score_threshold,
    )

    return {
        **state,
        "dense_results": dense_results,
        "graph_results": graph_results,
        "merged_results": merged_results,
    }
