from fastapi import APIRouter, Request

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.repositories.audit_log_repo import AuditLogRepository
from app.schemas.audit_log import AuditLogCreate, AuditLogResponse

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.post("", response_model=AuditLogResponse, status_code=201)
async def create_audit_log(
    body: AuditLogCreate,
    user_id: CurrentUserIdDep,
    db: DbDep,
    request: Request,
):
    repo = AuditLogRepository(db)
    ip_address = request.client.host if request.client else None
    return await repo.create(
        user_id=user_id,
        action=body.action,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        extra_data=body.extra_data,
        ip_address=ip_address,
    )


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    user_id: CurrentUserIdDep,
    db: DbDep,
):
    repo = AuditLogRepository(db)
    return await repo.list_by_user(user_id)
