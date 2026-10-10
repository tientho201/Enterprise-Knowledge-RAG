import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Giới hạn độ dài cho bản ghi do CLIENT gửi lên (POST /audit-logs). `action` và
# `resource_id` khớp đúng độ rộng cột trong models/audit_log.py (String(255) / String(36))
# để request quá dài nhận 422 ở tầng validate thay vì lỗi DB khi INSERT trên Postgres.
AUDIT_ACTION_MAX_LENGTH = 255
AUDIT_RESOURCE_ID_MAX_LENGTH = 36
# Độ dài tối đa của extra_data sau khi serialize JSON (tính theo ký tự).
AUDIT_EXTRA_DATA_MAX_JSON_LENGTH = 2000

# Loại bản ghi client được phép tự ghi. "query" / "document" (và mọi loại khác) chỉ do
# server ghi (chat_service, document_service) nên bị từ chối ở đây.
ClientAuditResourceType = Literal["config", "research"]


class AuditLogCreate(BaseModel):
    """Body của POST /audit-logs — bản ghi audit do client tự khai, KHÔNG tin cậy."""

    action: str = Field(min_length=1, max_length=AUDIT_ACTION_MAX_LENGTH)
    resource_type: ClientAuditResourceType
    resource_id: str | None = Field(default=None, max_length=AUDIT_RESOURCE_ID_MAX_LENGTH)
    extra_data: dict | None = None

    @field_validator("extra_data")
    @classmethod
    def _limit_extra_data_size(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        size = len(json.dumps(value, ensure_ascii=False))
        if size > AUDIT_EXTRA_DATA_MAX_JSON_LENGTH:
            raise ValueError(
                f"extra_data quá lớn ({size} ký tự JSON, tối đa {AUDIT_EXTRA_DATA_MAX_JSON_LENGTH})"
            )
        return value


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
