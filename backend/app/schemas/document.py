from datetime import datetime

from pydantic import BaseModel

from app.models.document import DocumentStatus, DocumentType


class DocumentResponse(BaseModel):
    id: str
    name: str
    type: DocumentType
    status: DocumentStatus
    version: int
    source: str | None
    file_size: int | None
    is_active: bool
    conversation_id: str | None = None
    conversation_title: str | None = None
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


class AssignConversationRequest(BaseModel):
    # None → gỡ khỏi hội thoại (đưa về kho tổng)
    conversation_id: str | None = None
