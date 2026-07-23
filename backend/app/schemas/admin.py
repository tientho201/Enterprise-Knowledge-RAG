from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.user import UserRole


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class DashboardStats(BaseModel):
    total_users: int
    total_documents: int
    total_conversations: int
    total_messages: int
    documents_by_status: dict[str, int]


class AnalyticsResponse(BaseModel):
    period: str
    total_queries: int
    avg_response_time_ms: float
    total_tokens_used: int
    top_documents: list[dict[str, Any]]


class JobResponse(BaseModel):
    id: str
    task_name: str
    status: str
    created_at: datetime | None
    result: Any | None
