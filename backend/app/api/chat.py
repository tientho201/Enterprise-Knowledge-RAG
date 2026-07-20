from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.dependencies import CurrentUserDep, CurrentUserIdDep, DbDep
from app.core.rate_limit import rate_limiter
from app.models.user import UserRole
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationDetailResponse,
    ConversationResponse,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_model=ChatResponse,
    dependencies=[
        Depends(rate_limiter(settings.CHAT_RATE_LIMIT_PER_MINUTE, 60, "chat")),
    ],
)
async def chat(body: ChatRequest, user: CurrentUserDep, db: DbDep):
    import logging

    logging.getLogger(__name__).info(
        f"Incoming ChatRequest: user_id={user.id}, message={repr(body.message)}, "
        f"conversation_id={body.conversation_id}, search_tool={body.search_tool}, document_ids={body.document_ids}"
    )
    service = ChatService(db)
    return await service.chat(
        user.id,
        body.message,
        body.conversation_id,
        body.search_tool,
        body.document_ids,
        is_admin=(user.role == UserRole.admin),
    )


@router.post(
    "/stream",
    dependencies=[
        Depends(rate_limiter(settings.CHAT_RATE_LIMIT_PER_MINUTE, 60, "chat")),
    ],
)
async def chat_stream(body: ChatRequest, user: CurrentUserDep, db: DbDep):
    """Streaming SSE: câu trả lời hiện dần token-by-token (giảm thời gian chờ chữ đầu)."""
    service = ChatService(db)
    stream = service.chat_stream(
        user.id,
        body.message,
        body.conversation_id,
        body.search_tool,
        body.document_ids,
        is_admin=(user.role == UserRole.admin),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/history", response_model=list[ConversationResponse])
async def history(user_id: CurrentUserIdDep, db: DbDep):
    service = ChatService(db)
    return await service.get_history(user_id)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(conversation_id: str, user_id: CurrentUserIdDep, db: DbDep):
    service = ChatService(db)
    return await service.get_conversation(user_id, conversation_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, user_id: CurrentUserIdDep, db: DbDep):
    service = ChatService(db)
    await service.delete_conversation(user_id, conversation_id)
