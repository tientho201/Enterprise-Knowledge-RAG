from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus, DocumentType


class DocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, doc_id: str) -> Document | None:
        result = await self.db.execute(
            select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        name: str,
        doc_type: DocumentType,
        storage_path: str | None = None,
        source: str | None = None,
        file_size: int | None = None,
        owner_id: str | None = None,
        conversation_id: str | None = None,
    ) -> Document:
        doc = Document(
            name=name,
            type=doc_type,
            storage_path=storage_path,
            source=source,
            file_size=file_size,
            owner_id=owner_id,
            conversation_id=conversation_id,
        )
        self.db.add(doc)
        await self.db.flush()
        await self.db.refresh(doc)
        return doc

    async def update_status(
        self,
        doc_id: str,
        status: DocumentStatus,
        error_message: str | None = None,
    ) -> Document | None:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.status = status
            if error_message is not None:
                doc.error_message = error_message
            await self.db.flush()
        return doc

    async def set_active(self, doc_id: str, is_active: bool) -> Document | None:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.is_active = is_active
            await self.db.flush()
        return doc

    async def set_conversation(self, doc_id: str, conversation_id: str | None) -> Document | None:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.conversation_id = conversation_id
            await self.db.flush()
        return doc

    async def soft_delete(self, doc_id: str) -> bool:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.deleted_at = datetime.now(UTC)
            await self.db.flush()
            return True
        return False

    async def list_with_conversation(
        self, skip: int = 0, limit: int = 20, owner_id: str | None = None
    ) -> tuple[list[tuple[Document, str | None]], int]:
        """List active (chưa xóa) docs kèm tên hội thoại đã gắn.

        `owner_id=None` → tất cả (admin); có giá trị → chỉ doc của user đó.
        Trả về list[(Document, conversation_title)] để service dựng DocumentResponse.
        """
        base_query = select(Document).where(Document.deleted_at.is_(None))
        if owner_id is not None:
            base_query = base_query.where(Document.owner_id == owner_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        rows_query = (
            select(Document, Conversation.title)
            .outerjoin(Conversation, Document.conversation_id == Conversation.id)
            .where(Document.deleted_at.is_(None))
        )
        if owner_id is not None:
            rows_query = rows_query.where(Document.owner_id == owner_id)
        rows_query = rows_query.order_by(Document.created_at.desc()).offset(skip).limit(limit)

        rows = await self.db.execute(rows_query)
        return [(doc, title) for doc, title in rows.all()], total
