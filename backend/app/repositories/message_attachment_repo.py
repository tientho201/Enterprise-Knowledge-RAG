from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.message_attachment import MessageAttachment


class MessageAttachmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self, owner_id: str, storage_path: str, content_type: str, file_size: int
    ) -> MessageAttachment:
        attachment = MessageAttachment(
            owner_id=owner_id,
            storage_path=storage_path,
            content_type=content_type,
            file_size=file_size,
        )
        self.db.add(attachment)
        await self.db.flush()
        await self.db.refresh(attachment)
        return attachment

    async def get_owned(self, ids: list[str], owner_id: str) -> list[MessageAttachment]:
        """Chỉ trả về attachment thuộc chính owner_id — data isolation trước khi gắn
        vào message hoặc gửi ảnh cho LLM."""
        if not ids:
            return []
        result = await self.db.execute(
            select(MessageAttachment).where(
                MessageAttachment.id.in_(ids),
                MessageAttachment.owner_id == owner_id,
            )
        )
        return list(result.scalars().all())

    async def attach_to_message(self, ids: list[str], message_id: str, owner_id: str) -> None:
        """Gắn các ảnh đã upload (message_id=NULL) vào tin nhắn user vừa lưu."""
        if not ids:
            return
        attachments = await self.get_owned(ids, owner_id)
        for attachment in attachments:
            attachment.message_id = message_id
        await self.db.flush()

    async def list_by_message_ids(self, message_ids: list[str]) -> list[MessageAttachment]:
        if not message_ids:
            return []
        result = await self.db.execute(
            select(MessageAttachment).where(MessageAttachment.message_id.in_(message_ids))
        )
        return list(result.scalars().all())

    async def list_storage_paths_by_conversation(self, conversation_id: str) -> list[str]:
        """S3 keys của mọi ảnh thuộc mọi tin nhắn trong 1 hội thoại — dùng để dọn S3
        SAU khi record DB đã xóa (xem ChatService.delete_conversation)."""
        result = await self.db.execute(
            select(MessageAttachment.storage_path)
            .join(Message, Message.id == MessageAttachment.message_id)
            .where(Message.conversation_id == conversation_id)
        )
        return list(result.scalars().all())
