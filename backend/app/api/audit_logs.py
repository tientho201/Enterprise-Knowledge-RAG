from fastapi import APIRouter, Depends, Request

from app.core.config import settings
from app.core.dependencies import CurrentUserIdDep, DbDep
from app.core.rate_limit import rate_limiter
from app.schemas.audit_log import AuditLogCreate, AuditLogResponse
from app.services.audit_log_service import AuditLogService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.post(
    "",
    response_model=AuditLogResponse,
    status_code=201,
    dependencies=[
        # Giá trị <= 0 KHÔNG có nghĩa "tắt giới hạn": với rate_limiter hiện có, mọi request
        # đều vượt ngưỡng nên bị 429 (tức khoá việc client tự ghi log). Lưu ý rate_limiter
        # fail-open khi Redis lỗi.
        Depends(rate_limiter(settings.AUDIT_LOG_RATE_LIMIT_PER_MINUTE, 60, "audit-log")),
    ],
)
async def create_audit_log(
    body: AuditLogCreate,
    user_id: CurrentUserIdDep,
    db: DbDep,
    request: Request,
):
    """Client tự ghi một bản ghi audit (chỉ loại config / research).

    Server luôn gắn extra_data.source = "client"; các khoá dành riêng bị loại bỏ.
    """
    ip_address = request.client.host if request.client else None
    return await AuditLogService(db).create_client_log(user_id, body, ip_address=ip_address)


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    user_id: CurrentUserIdDep,
    db: DbDep,
):
    return await AuditLogService(db).list_for_user(user_id)
