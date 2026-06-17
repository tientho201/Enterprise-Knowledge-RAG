from typing import TypedDict

from app.rag.retriever import RetrievedChunk


class AgentState(TypedDict):
    query: str
    intent: str                          # "rag" | "chitchat" | "out_of_scope"
    rewritten_query: str | None
    dense_results: list[RetrievedChunk]
    sparse_results: list[RetrievedChunk]
    merged_results: list[RetrievedChunk]
    reranked_results: list[RetrievedChunk]
    citations: list[dict]
    final_answer: str | None
    confidence_score: float
    retry_count: int
