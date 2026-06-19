"""
Retriever node: runs hybrid (dense + graph) search and populates state.

dense_results  — raw Qdrant ANN hits
graph_results  — Neo4j-expanded chunks (NEXT_CHUNK / REFERENCES traversal)
merged_results — hybrid-scored union, sorted by descending score
"""
from app.agents.state import AgentState
from app.ingestion.embedder import get_embedder
from app.rag.retriever import HybridRetriever


async def retriever_node(state: AgentState) -> AgentState:
    query = state.get("rewritten_query") or state["query"]

    embedder = get_embedder()
    retriever = HybridRetriever()

    query_embedding = embedder.embed_query(query)

    # Dense seeds (Qdrant)
    dense_results = retriever._dense_search(query_embedding)

    # Graph expansion (Neo4j) — returns {} if Neo4j is unavailable
    seed_ids = [r.chunk_id for r in dense_results]
    graph_map = retriever._graph_search(seed_ids)
    graph_results = [chunk for chunk, _ in graph_map.values()]

    # Merge + hybrid score
    merged_results = retriever.retrieve(query, query_embedding)

    return {
        **state,
        "dense_results": dense_results,
        "graph_results": graph_results,
        "merged_results": merged_results,
    }
