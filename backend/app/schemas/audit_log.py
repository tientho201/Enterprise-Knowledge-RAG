from datetime import datetime
from pydantic import BaseModel


class AuditLogCreate(BaseModel):
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    extra_data: dict | None = None


class AuditLogResponse(BaseModel):
    id: str
    user_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    extra_data: dict | None
    ip_address: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
