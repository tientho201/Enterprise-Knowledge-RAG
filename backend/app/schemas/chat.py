from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.message import MessageRole


class AttachmentUploadResponse(BaseModel):
    """Kết quả upload 1 ảnh gửi kèm chat — id dùng để tham chiếu trong ChatRequest.image_ids."""

    id: str
    url: str
    content_type: str


class AttachmentSchema(BaseModel):
    """Ảnh đính kèm hiển thị lại khi render lịch sử hội thoại."""

    id: str
    url: str
    content_type: str

    model_config = {"from_attributes": True}


class CitationSchema(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    # Optional metadata: nhiều nguồn (RAG chunk) không có → default None để Pydantic
    # KHÔNG coi là bắt buộc (X | None không có default vẫn là required).
    page_number: int | None = None
    section_title: str | None = None
    source_link: str | None = None
    content_snippet: str

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    search_tool: bool | None = Field(default=False, alias="searchTool")
    document_ids: list[str] | None = Field(default=None, alias="documentIds")
    # Ảnh gửi kèm (vision) — id trả về từ POST /chat/images. Tối đa 3 ảnh/tin nhắn
    # (chặn phình chi phí/độ trễ vision token). Ngữ cảnh tạm, KHÔNG phải tài liệu thư viện.
    image_ids: list[str] | None = Field(default=None, alias="imageIds", max_length=3)
    # Chế độ tra cứu chọn ở panel Cấu hình. None -> hành vi mặc định hiện tại (hybrid,
    # không đổi gì). "advanced" là chế độ duy nhất có gate (xem core/plan_gate.py) —
    # thêm graph-augmented retrieval qua Provision layer (rag/citation_retriever.py,
    # traverse VIEN_DAN 1-2 hop) bên cạnh hybrid, KHÔNG thay thế hybrid.
    search_mode: Literal["hybrid", "vector", "keyword", "advanced"] | None = Field(
        default=None, alias="searchMode"
    )
    # Tuning từ panel Cấu hình. None → dùng default trong config.py.
    # top_k: số chunk cuối đưa vào generator (override RERANK_TOP_K).
    # similarity_threshold: điểm cosine tối thiểu cho dense search (Qdrant score_threshold).
    top_k: int | None = Field(default=None, alias="topK", ge=1, le=50)
    similarity_threshold: float | None = Field(
        default=None, alias="similarityThreshold", ge=0.0, le=1.0
    )
    # None/rỗng → dùng SYSTEM_PROMPT mặc định trong agents/generator.py.
    system_prompt: str | None = Field(default=None, alias="systemPrompt", max_length=4000)
    # BYOM (bring-your-own-model) từ panel Cấu hình — OpenAI-compatible passthrough.
    # api_key rỗng/None → bỏ qua model/base_url, luôn dùng get_llm() (model mặc định server).
    # api_key KHÔNG được lưu ở server, chỉ dùng trong phạm vi request này.
    model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, alias="apiKey", max_length=500)
    base_url: str | None = Field(default=None, alias="baseUrl", max_length=500)

    model_config = {"populate_by_name": True, "from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    created_at: datetime
    citations: list[CitationSchema] = []
    attachments: list[AttachmentSchema] = []

    model_config = {"from_attributes": True}


class CitationGraphStep(BaseModel):
    """1 bước traversal VIEN_DAN/VIEN_DAN_VAN_BAN — audit trail cho chế độ "Nâng cao"
    (rag/citation_retriever.py). Chỉ khác rỗng khi search_mode="advanced"."""

    from_address: str
    to_address: str
    relation: str
    hops: int
    in_context: bool


class SuggestedDocument(BaseModel):
    """Tài liệu được viện dẫn nhưng KHÔNG gộp vào context — chưa gắn vào hội thoại
    này (in_library=True, document_id có giá trị) hoặc chưa có trong thư viện owner
    (in_library=False, document_id=None). Chỉ khác rỗng khi search_mode="advanced"."""

    document_code: str
    document_id: str | None = None
    name: str | None = None
    in_library: bool
    cited_from: str


class CitationGraphNode(BaseModel):
    """1 node trong đồ thị dẫn chiếu (UI chế độ "Nâng cao") — dedup theo address,
    1 entry cho mỗi legal_address/document xuất hiện trong citation_graph_path.
    Xem rag/citation_retriever.py::_classify. Chỉ khác rỗng khi search_mode="advanced".

    address:      khoá nội bộ (legal_address) — CHỈ dùng để khớp with from_address/
                  to_address của CitationGraphStep, KHÔNG hiển thị thô cho người dùng.
    label:        nhãn dễ đọc dựng sẵn ở server (vd "Điều 5 Khoản 2, Nghị định 88/2019").
    node_type:    "anchor" (điểm neo — Provision khớp dense search trực tiếp),
                  "in_context" (lấy qua viện dẫn, nội dung đã gộp vào câu trả lời),
                  "out_of_scope" (không góp nội dung — placeholder chưa từng ingest,
                  HOẶC tài liệu thật đã có trong thư viện owner nhưng chưa gắn vào
                  hội thoại này; phân biệt qua in_library).
    in_library:   chỉ có ý nghĩa khi node_type="out_of_scope" — True nếu tài liệu đã
                  có trong thư viện owner (FE hiện nút gắn vào hội thoại), False nếu
                  chưa từng được ingest (FE hiện gợi ý tải lên).
    content:      nguyên văn điều khoản — CHỈ có khi node_type != "out_of_scope"
                  (anchor/in_context). None cho out_of_scope, kể cả khi in_library=True
                  — nội dung tài liệu chưa gắn vào hội thoại này không được lộ qua đây.
    """

    address: str
    label: str
    document_id: str | None = None
    document_name: str | None = None
    node_type: Literal["anchor", "in_context", "out_of_scope"]
    in_library: bool
    content: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageResponse
    # Additive — rỗng ([]) trừ khi search_mode="advanced" (chế độ "Nâng cao"), FE cũ
    # bỏ qua field không biết nên không vỡ tương thích ngược.
    citation_graph_path: list[CitationGraphStep] = []
    citation_graph_nodes: list[CitationGraphNode] = []
    suggested_documents: list[SuggestedDocument] = []


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationDetailResponse(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}
