from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation
from app.models.message import Message, MessageRole

# Vị trí của tin nhắn trong một lượt hỏi-đáp: user (0) -> system (1) -> assistant (2).
# Dùng làm khoá phụ khi hai tin nhắn trùng `created_at` (bảng `messages` không có cột
# số thứ tự, còn `id` là uuid4 ngẫu nhiên nên không phản ánh thứ tự ghi).
_ROLE_TURN_ORDER = case(
    (Message.role == MessageRole.user, 0),
    (Message.role == MessageRole.assistant, 2),
    else_=1,
)


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

    async def list_recent_messages(
        self, conversation_id: str, user_id: str, limit: int
    ) -> list[Message]:
        """`limit` tin nhắn MỚI nhất của hội thoại, trả theo thứ tự cũ -> mới.

        - Cô lập theo chủ hội thoại: JOIN `Conversation` và ép `Conversation.user_id ==
          user_id`; hội thoại của user khác (hoặc không tồn tại) -> `[]`, không raise.
        - `limit <= 0` -> `[]`, không chạm DB.
        - Thứ tự xác định khi trùng `created_at`: khoá phụ là vai trò (user trước
          assistant — đúng thứ tự trong một lượt hỏi-đáp), cuối cùng là `id`.
        - Chỉ nạp cột của `Message`. `citations`/`attachments` KHÔNG được nạp (lazy);
          đừng truy cập chúng trên kết quả — trong AsyncSession sẽ lỗi MissingGreenlet.
        - `Message.content` trả về THÔ: tin nhắn assistant còn marker
          `<!--citations:...-->` ở cuối. Nơi gọi tự bóc marker trước khi đưa vào prompt.
        - `conversations`/`messages` không có `deleted_at` (xoá cứng, cascade), nên không
          có bộ lọc soft-delete ở đây.
        """
        if limit <= 0:
            return []
        result = await self.db.execute(
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Message.conversation_id == conversation_id,
                Conversation.user_id == user_id,
            )
            .order_by(
                Message.created_at.desc(),
                _ROLE_TURN_ORDER.desc(),
                Message.id.desc(),
            )
            .limit(limit)
        )
        newest_first = list(result.scalars().all())
        newest_first.reverse()
        return newest_first

    async def update_title(self, conv_id: str, title: str) -> None:
        conv_result = await self.db.execute(select(Conversation).where(Conversation.id == conv_id))
        conv = conv_result.scalar_one_or_none()
        if conv:
            conv.title = title
            await self.db.flush()
