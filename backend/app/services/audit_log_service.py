"""
Audit log service — business logic cho các bản ghi audit do CLIENT gửi qua POST /audit-logs.

Bản ghi do server tự ghi (truy vấn RAG, upload/xoá/reindex tài liệu, cờ DLP) KHÔNG đi qua
service này: chat_service / document_service gọi thẳng AuditLogRepository. Nhờ vậy mọi
ràng buộc ở đây chỉ áp cho dữ liệu client tự khai, không ảnh hưởng log hệ thống.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.repositories.audit_log_repo import AuditLogRepository
from app.schemas.audit_log import AuditLogCreate

# Khoá trong extra_data chỉ server được ghi. Client gửi lên thì bị LOẠI BỎ (không báo lỗi):
#   - source:               nguồn bản ghi, server tự gắn bên dưới
#   - dlp_flag, dlp_reason: cờ DLP do chat_service ghi (agents/dlp.py), admin dùng để tra soát
RESERVED_EXTRA_KEYS = frozenset({"source", "dlp_flag", "dlp_reason"})

# Giá trị extra_data["source"] của mọi bản ghi tạo qua POST /audit-logs. Bản ghi do server
# tự ghi không có khoá "source".
CLIENT_SOURCE = "client"


def _is_reserved(key: object) -> bool:
    """So khớp không phân biệt hoa thường / khoảng trắng để "DLP_Flag", " source " cũng bị loại."""
    return isinstance(key, str) and key.strip().lower() in RESERVED_EXTRA_KEYS


class AuditLogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = AuditLogRepository(db)

    async def create_client_log(
        self,
        user_id: str,
        body: AuditLogCreate,
        ip_address: str | None = None,
    ) -> AuditLog:
        """Ghi một bản ghi audit do client tự khai, luôn đánh dấu source = "client".

        Loại bỏ các khoá dành riêng khỏi extra_data rồi gắn source ở phía server, nên client
        không thể tự đặt source hay giả cờ DLP. Loại bản ghi và độ dài đã được
        AuditLogCreate kiểm ở tầng schema.
        """
        extra_data = {
            key: value for key, value in (body.extra_data or {}).items() if not _is_reserved(key)
        }
        extra_data["source"] = CLIENT_SOURCE

        return await self.repo.create(
            user_id=user_id,
            action=body.action,
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            extra_data=extra_data,
            ip_address=ip_address,
        )

    async def list_for_user(self, user_id: str) -> list[AuditLog]:
        """Log của chính user (cả log server ghi lẫn log client ghi), mới nhất trước."""
        return await self.repo.list_by_user(user_id)
