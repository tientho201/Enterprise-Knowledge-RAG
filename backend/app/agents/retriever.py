"""Retriever node: runs hybrid search and populates results in state."""
from app.agents.state import AgentState
from app.ingestion.embedder import get_embedder
from app.rag.retriever import HybridRetriever


async def retriever_node(state: AgentState) -> AgentState:
    query = state.get("rewritten_query") or state["query"]

    embedder = get_embedder()
    retriever = HybridRetriever()

    query_embedding = embedder.embed_query(query)
    results = retriever.retrieve(query, query_embedding)

    return {
        **state,
        "merged_results": results,
        "dense_results": results,
        "sparse_results": [],
    }
