from typing import TypedDict

from app.rag.retriever import RetrievedChunk


class AgentState(TypedDict):
    query: str
    intent: str  # "rag" | "chitchat" | "out_of_scope"
    rewritten_query: str | None
    dense_results: list[RetrievedChunk]  # raw Qdrant ANN results
    graph_results: list[RetrievedChunk]  # Neo4j graph-expanded results
    merged_results: list[RetrievedChunk]  # hybrid-scored + merged set
    reranked_results: list[RetrievedChunk]
    citations: list[dict]
    final_answer: str | None
    confidence_score: float
    retry_count: int
    search_tool: bool | None
    document_ids: list[str] | None
    # Data isolation: chỉ truy hồi chunk của owner này. None = admin/không filter.
    owner_id: str | None
    # Tuning từ UI (None → dùng default config). top_k = số chunk cuối (rerank);
    # similarity_threshold = điểm cosine tối thiểu cho dense search.
    top_k: int | None
    similarity_threshold: float | None
    # System prompt tùy chỉnh từ panel Cấu hình. None/rỗng → dùng SYSTEM_PROMPT mặc định (generator.py).
    system_prompt: str | None
    # BYOM passthrough (xem llm/factory.py::get_llm_for_request). api_key None → luôn get_llm().
    model: str | None
    api_key: str | None
    base_url: str | None
    # Ảnh gửi kèm tin nhắn (vision, ngữ cảnh tạm — KHÔNG phải tài liệu thư viện).
    # Data URI base64 sẵn sàng đưa vào content part {"type":"image_url","image_url":{"url":...}}.
    # None/rỗng → hành vi y hệt trước đây (regression-safe).
    image_data_urls: list[str] | None
