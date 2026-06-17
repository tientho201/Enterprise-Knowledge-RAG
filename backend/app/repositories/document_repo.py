from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ) -> Document:
        doc = Document(
            name=name,
            type=doc_type,
            storage_path=storage_path,
            source=source,
            file_size=file_size,
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

    async def soft_delete(self, doc_id: str) -> bool:
        doc = await self.get_by_id(doc_id)
        if doc:
            doc.deleted_at = datetime.now(UTC)
            await self.db.flush()
            return True
        return False

    async def list_active(
        self, skip: int = 0, limit: int = 20
    ) -> tuple[list[Document], int]:
        base_query = select(Document).where(Document.deleted_at.is_(None))
        count_result = await self.db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
        total = count_result.scalar_one()
        result = await self.db.execute(
            base_query.order_by(Document.created_at.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all()), total
