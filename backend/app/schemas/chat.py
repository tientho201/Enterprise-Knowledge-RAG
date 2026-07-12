from datetime import datetime

from pydantic import BaseModel, Field

from app.models.message import MessageRole


class CitationSchema(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    page_number: int | None
    section_title: str | None
    source_link: str | None
    content_snippet: str

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    search_tool: bool | None = Field(default=False, alias="searchTool")
    document_ids: list[str] | None = Field(default=None, alias="documentIds")

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
