from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus, DocumentType
from app.models.document_conversation import DocumentConversation


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
        )
        self.db.add(doc)
        await self.db.flush()
        if conversation_id:
            self.db.add(DocumentConversation(document_id=doc.id, conversation_id=conversation_id))
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

    async def add_conversation_link(self, doc_id: str, conversation_id: str) -> None:
        """Gắn thêm 1 hội thoại vào tài liệu (idempotent, không xóa liên kết cũ)."""
        exists = await self.db.execute(
            select(DocumentConversation.document_id).where(
                DocumentConversation.document_id == doc_id,
                DocumentConversation.conversation_id == conversation_id,
            )
        )
        if exists.scalar_one_or_none() is None:
            self.db.add(DocumentConversation(document_id=doc_id, conversation_id=conversation_id))
            await self.db.flush()

    async def set_conversations(self, doc_id: str, conversation_ids: list[str]) -> None:
        """Thay toàn bộ liên kết hội thoại của tài liệu bằng danh sách mới (rỗng → gỡ hết)."""
        await self.db.execute(
            delete(DocumentConversation).where(DocumentConversation.document_id == doc_id)
        )
        for conv_id in dict.fromkeys(conversation_ids):  # dedupe, giữ thứ tự
            self.db.add(DocumentConversation(document_id=doc_id, conversation_id=conv_id))
        await self.db.flush()

    async def soft_delete(self, doc_id: str) -> bool:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.deleted_at = datetime.now(UTC)
            await self.db.flush()
            return True
        return False

    async def list_document_ids_for_conversation(
        self, conversation_id: str, owner_id: str | None = None
    ) -> list[str]:
        """ID các tài liệu (chưa xóa) gắn vào 1 hội thoại — dùng cho graph explorer.

        `owner_id=None` → mọi doc của hội thoại (admin); có giá trị → chỉ doc của
        user đó (data isolation, mirror `HybridRetriever._graph_search`).
        """
        query = (
            select(Document.id)
            .join(DocumentConversation, DocumentConversation.document_id == Document.id)
            .where(
                DocumentConversation.conversation_id == conversation_id,
                Document.deleted_at.is_(None),
            )
        )
        if owner_id is not None:
            query = query.where(Document.owner_id == owner_id)
        rows = await self.db.execute(query)
        return list(rows.scalars().all())

    async def list_with_conversations(
        self, skip: int = 0, limit: int = 20, owner_id: str | None = None
    ) -> tuple[list[Document], int]:
        """List active (chưa xóa) docs kèm các hội thoại đã gắn (many-to-many).

        `owner_id=None` → tất cả (admin); có giá trị → chỉ doc của user đó.
        `doc.conversations` (eager-loaded) chứa list[Conversation] để service dựng DocumentResponse.
        """
        base_query = select(Document).where(Document.deleted_at.is_(None))
        if owner_id is not None:
            base_query = base_query.where(Document.owner_id == owner_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()

        rows_query = select(Document).where(Document.deleted_at.is_(None))
        if owner_id is not None:
            rows_query = rows_query.where(Document.owner_id == owner_id)
        rows_query = rows_query.order_by(Document.created_at.desc()).offset(skip).limit(limit)

        rows = await self.db.execute(rows_query)
        return list(rows.scalars().all()), total
