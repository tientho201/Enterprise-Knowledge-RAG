from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.core.plan_gate import can_use_advanced_search
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository
from app.schemas.admin import DashboardStats, UpdateUserRoleRequest
from app.schemas.auth import UserResponse
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(user_id: str, db) -> None:
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if not user or user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        plan=user.plan,
        can_use_advanced_search=can_use_advanced_search(user),
    )


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(user_id: CurrentUserIdDep, db: DbDep):
    await require_admin(user_id, db)

    total_users = (await db.execute(select(func.count(User.id)))).scalar_one()
    total_docs = (
        await db.execute(select(func.count(Document.id)).where(Document.deleted_at.is_(None)))
    ).scalar_one()
    total_convs = (await db.execute(select(func.count(Conversation.id)))).scalar_one()
    total_msgs = (await db.execute(select(func.count(Message.id)))).scalar_one()

    from app.models.document import DocumentStatus

    status_counts = {}
    for s in DocumentStatus:
        count = (
            await db.execute(
                select(func.count(Document.id)).where(
                    Document.status == s, Document.deleted_at.is_(None)
                )
            )
        ).scalar_one()
        status_counts[s.value] = count

    return DashboardStats(
        total_users=total_users,
        total_documents=total_docs,
        total_conversations=total_convs,
        total_messages=total_msgs,
        documents_by_status=status_counts,
    )


@router.get("/jobs")
async def list_jobs(user_id: CurrentUserIdDep, db: DbDep):
    await require_admin(user_id, db)
    inspect = celery_app.control.inspect()
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}
    return {"active": active, "reserved": reserved}


@router.get("/users", response_model=list[UserResponse])
async def list_users(user_id: CurrentUserIdDep, db: DbDep):
    await require_admin(user_id, db)
    users = await UserRepository(db).list_all(limit=200)
    return [_to_user_response(u) for u in users]


@router.patch("/users/{target_user_id}/role", response_model=UserResponse)
async def update_user_role(
    target_user_id: str, body: UpdateUserRoleRequest, user_id: CurrentUserIdDep, db: DbDep
):
    await require_admin(user_id, db)
    user = await UserRepository(db).update_role(target_user_id, body.role)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _to_user_response(user)
