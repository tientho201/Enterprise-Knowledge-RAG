from fastapi import APIRouter

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationDetailResponse,
    ConversationResponse,
)
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, user_id: CurrentUserIdDep, db: DbDep):
    import logging
    logging.getLogger(__name__).info(
        f"Incoming ChatRequest: user_id={user_id}, message={repr(body.message)}, "
        f"conversation_id={body.conversation_id}, search_tool={body.search_tool}"
    )
    service = ChatService(db)
    return await service.chat(user_id, body.message, body.conversation_id, body.search_tool)


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
