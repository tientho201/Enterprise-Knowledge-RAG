from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus, DocumentType


class ConversationRef(BaseModel):
    id: str
    title: str | None = None

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: str
    name: str
    type: DocumentType
    status: DocumentStatus
    version: int
    source: str | None
    file_size: int | None
    is_active: bool
    conversations: list[ConversationRef] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    page_size: int


class ReindexRequest(BaseModel):
    document_id: str


class SetActiveRequest(BaseModel):
    is_active: bool


class AddConversationRequest(BaseModel):
    conversation_id: str


class SetConversationsRequest(BaseModel):
    # Danh sách đầy đủ hội thoại gắn với tài liệu — thay thế toàn bộ liên kết cũ.
    # [] → gỡ khỏi tất cả hội thoại (đưa về kho tổng).
    conversation_ids: list[str] = []
