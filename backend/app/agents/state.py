from typing import Literal, TypedDict

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
    # Chế độ tra cứu chọn ở panel Cấu hình (mirror schemas/chat.py::ChatRequest.search_mode).
    # None/"hybrid"/"vector"/"keyword" → retriever_node chạy hybrid như cũ. "advanced" →
    # thêm graph-augmented retrieval qua Provision layer (rag/citation_retriever.py) —
    # ĐÃ qua gate plan Pro ở tầng route (core/plan_gate.py) trước khi tới đây.
    search_mode: Literal["hybrid", "vector", "keyword", "advanced"] | None
    # Audit trail traversal VIEN_DAN/VIEN_DAN_VAN_BAN — rỗng khi search_mode != "advanced"
    # hoặc citation graph không tìm thấy anchor nào. Xem rag/citation_retriever.py.
    citation_graph_path: list[dict]
    # Node registry cho UI đồ thị (1 entry/address, dedup) — xem
    # rag/citation_retriever.py::_classify và schemas/chat.py::CitationGraphNode.
    citation_graph_nodes: list[dict]
    # Tài liệu được viện dẫn nhưng KHÔNG gộp vào context (chưa gắn hội thoại này, hoặc
    # chưa có trong thư viện owner) — trả qua SSE để FE gợi ý người dùng đính kèm/tải lên.
    suggested_documents: list[dict]
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
