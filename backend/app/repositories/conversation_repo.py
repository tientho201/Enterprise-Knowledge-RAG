from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, conv_id: str, user_id: str) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.id == conv_id, Conversation.user_id == user_id)
            .options(
                selectinload(Conversation.messages).selectinload(Message.citations),
                selectinload(Conversation.messages).selectinload(Message.attachments),
            )
        )
        return result.scalar_one_or_none()

    async def get_owner_id(self, conv_id: str) -> str | None:
        """user_id sở hữu hội thoại (None nếu không tồn tại). Query nhẹ — không nạp
        messages/citations như `get_by_id`. Dùng để verify quyền ở graph explorer."""
        result = await self.db.execute(
            select(Conversation.user_id).where(Conversation.id == conv_id)
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: str, title: str | None = None) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        self.db.add(conv)
        await self.db.flush()
        await self.db.refresh(conv)
        return conv

    async def list_by_user(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def delete(self, conv_id: str, user_id: str) -> bool:
        conv = await self.get_by_id(conv_id, user_id)
        if conv:
            await self.db.delete(conv)
            await self.db.flush()
            return True
        return False

    async def add_message(
        self,
        conversation_id: str,
        role: MessageRole,
        content: str,
    ) -> Message:
        msg = Message(conversation_id=conversation_id, role=role, content=content)
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def update_title(self, conv_id: str, title: str) -> None:
        conv_result = await self.db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = conv_result.scalar_one_or_none()
        if conv:
            conv.title = title
            await self.db.flush()
