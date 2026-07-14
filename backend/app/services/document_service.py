"""
Document service — business logic layer.

Storage split:
  - Raw files (PDF, DOCX, TXT) → AWS S3  (via s3_client async helpers)
  - Metadata (document records, audit logs) → Supabase / PostgreSQL (via repositories)
"""

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentType
from app.repositories.audit_log_repo import AuditLogRepository
from app.repositories.document_repo import DocumentRepository
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.storage.s3_client import (
    get_presigned_url_async,
    upload_bytes_async,
)

ALLOWED_CONTENT_TYPES: dict[str, DocumentType] = {
    "application/pdf": DocumentType.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.docx,
    "text/plain": DocumentType.txt,
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class DocumentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = DocumentRepository(db)
        self.audit = AuditLogRepository(db)

    # ── Upload ────────────────────────────────────────────────────────────────

    async def upload(self, file: UploadFile, user_id: str | None = None) -> DocumentResponse:
        """
        Validate → upload raw file to S3 → save metadata to Supabase → dispatch Celery task.
        """
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type: {file.content_type}. Allowed: pdf, docx, txt",
            )

        file_bytes = await file.read()
        if len(file_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds 50 MB limit",
            )

        # 1. Upload raw file to S3 (async, non-blocking)
        object_name = f"{uuid.uuid4()}/{file.filename}"
        await upload_bytes_async(object_name, file_bytes, content_type=file.content_type)

        # 2. Save document metadata to Supabase/PostgreSQL
        doc_type = ALLOWED_CONTENT_TYPES[file.content_type]
        doc = await self.repo.create(
            name=file.filename or "untitled",
            doc_type=doc_type,
            storage_path=object_name,  # S3 object key — used by Celery task to download
            file_size=len(file_bytes),
            owner_id=user_id,  # data isolation: gắn chủ sở hữu = người upload
        )

        # 3. Write audit log to Supabase
        await self.audit.create(
            user_id=user_id,
            action=f"Đã nạp tài liệu: {file.filename}",
            resource_type="document",
            resource_id=doc.id,
            extra_data={
                "file_size_kb": round(len(file_bytes) / 1024),
                "s3_path": object_name,
            },
        )

        # 4. Dispatch async ingestion (non-blocking) — Celery downloads from S3
        from app.workers.tasks.ingestion import ingest_document

        ingest_document.delay(doc.id, object_name)

        return DocumentResponse.model_validate(doc)

    # ── Ownership guard (data isolation) ──────────────────────────────────────

    async def _get_owned_or_404(self, doc_id: str, user_id: str, is_admin: bool):
        """Fetch document + enforce ownership.

        Trả 404 (KHÔNG 403) khi doc không tồn tại HOẶC user không phải chủ sở hữu — để
        không lộ sự tồn tại của doc người khác. Admin bỏ qua check (thấy/quản lý tất cả).
        """
        doc = await self.repo.get_by_id(doc_id)
        if not doc or (not is_admin and doc.owner_id != user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return doc

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get(self, doc_id: str, user_id: str, is_admin: bool = False) -> DocumentResponse:
        doc = await self._get_owned_or_404(doc_id, user_id, is_admin)
        return DocumentResponse.model_validate(doc)

    async def list_documents(
        self, user_id: str, is_admin: bool = False, page: int = 1, page_size: int = 20
    ) -> DocumentListResponse:
        skip = (page - 1) * page_size
        # Admin: owner_id=None → thấy tất cả. Ngược lại: chỉ doc của chính user.
        owner_filter = None if is_admin else user_id
        docs, total = await self.repo.list_active(skip=skip, limit=page_size, owner_id=owner_filter)
        return DocumentListResponse(
            items=[DocumentResponse.model_validate(d) for d in docs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_download_url(
        self, doc_id: str, user_id: str, is_admin: bool = False, expires_seconds: int = 3600
    ) -> str:
        """
        Generate a presigned S3 URL so the frontend can download the raw file directly
        without proxying through the API server.
        """
        doc = await self._get_owned_or_404(doc_id, user_id, is_admin)
        if not doc.storage_path:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No file stored for this document",
            )
        return await get_presigned_url_async(doc.storage_path, expires_seconds)

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete(self, doc_id: str, user_id: str, is_admin: bool = False) -> None:
        """
        Soft-delete metadata in Supabase first, then queue S3 + vector cleanup via Celery.
        S3 deletion is best-effort — handled in background task.
        """
        doc = await self._get_owned_or_404(doc_id, user_id, is_admin)

        doc_name = doc.name
        storage_path = doc.storage_path

        # 1. Soft-delete metadata in Supabase
        await self.repo.soft_delete(doc_id)

        # 2. Write audit log to Supabase
        await self.audit.create(
            user_id=user_id,
            action=f"Đã xóa tài liệu: {doc_name}",
            resource_type="document",
            resource_id=doc_id,
            extra_data={"s3_path": storage_path},
        )

        # 3. Queue: delete vectors (Qdrant + Neo4j) AND raw file from S3
        from app.workers.tasks.ingestion import delete_document_vectors

        delete_document_vectors.delay(doc_id, storage_path)

    # ── Reindex ───────────────────────────────────────────────────────────────

    async def reindex(self, doc_id: str, user_id: str, is_admin: bool = False) -> DocumentResponse:
        """
        Queue a full reindex: delete old vectors → re-download from S3 → re-ingest.
        S3 file is NOT deleted — only vector stores are cleared.
        """
        doc = await self._get_owned_or_404(doc_id, user_id, is_admin)
        if not doc.storage_path:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document has no S3 file — cannot reindex",
            )

        await self.audit.create(
            user_id=user_id,
            action=f"Đã yêu cầu reindex: {doc.name}",
            resource_type="document",
            resource_id=doc_id,
        )

        # Pass storage_path so the task can chain delete → ingest without extra DB call
        from app.workers.tasks.ingestion import reindex_document

        reindex_document.delay(doc_id, doc.storage_path)

        return DocumentResponse.model_validate(doc)
