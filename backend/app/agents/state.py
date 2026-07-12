from typing import TypedDict

from app.rag.retriever import RetrievedChunk


class AgentState(TypedDict):
    query: str
    intent: str                           # "rag" | "chitchat" | "out_of_scope"
    rewritten_query: str | None
    dense_results: list[RetrievedChunk]   # raw Qdrant ANN results
    graph_results: list[RetrievedChunk]   # Neo4j graph-expanded results
    merged_results: list[RetrievedChunk]  # hybrid-scored + merged set
    reranked_results: list[RetrievedChunk]
    citations: list[dict]
    final_answer: str | None
    confidence_score: float
    retry_count: int
    search_tool: bool | None
    document_ids: list[str] | None
