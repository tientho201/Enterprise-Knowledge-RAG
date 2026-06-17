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
