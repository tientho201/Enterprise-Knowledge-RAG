from datetime import datetime

from pydantic import BaseModel, Field

from app.models.message import MessageRole


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
    # Tuning từ panel Cấu hình. None → dùng default trong config.py.
    # top_k: số chunk cuối đưa vào generator (override RERANK_TOP_K).
    # similarity_threshold: điểm cosine tối thiểu cho dense search (Qdrant score_threshold).
    top_k: int | None = Field(default=None, alias="topK", ge=1, le=50)
    similarity_threshold: float | None = Field(
        default=None, alias="similarityThreshold", ge=0.0, le=1.0
    )

    model_config = {"populate_by_name": True, "from_attributes": True}


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    created_at: datetime
    citations: list[CitationSchema] = []

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageResponse


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
