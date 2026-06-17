from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from app.models.user import User, UserRole
from app.repositories.user_repo import UserRepository
from app.schemas.admin import DashboardStats
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
