import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentType
from app.repositories.document_repo import DocumentRepository
from app.schemas.document import DocumentListResponse, DocumentResponse
from app.storage.s3_client import get_s3_client

ALLOWED_CONTENT_TYPES = {
    "application/pdf": DocumentType.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.docx,
    "text/plain": DocumentType.txt,
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DocumentRepository(db)

    async def upload(self, file: UploadFile) -> DocumentResponse:
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported file type: {file.content_type}",
            )

        file_bytes = await file.read()
        if len(file_bytes) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds 50 MB limit",
            )

        s3 = get_s3_client()
        object_name = f"{uuid.uuid4()}/{file.filename}"
        s3.upload_bytes(object_name, file_bytes, content_type=file.content_type)

        doc_type = ALLOWED_CONTENT_TYPES[file.content_type]
        doc = await self.repo.create(
            name=file.filename,
            doc_type=doc_type,
            storage_path=object_name,
            file_size=len(file_bytes),
        )

        # Dispatch async ingestion task (non-blocking)
        from app.workers.tasks.ingestion import ingest_document
        ingest_document.delay(doc.id, object_name)

        return DocumentResponse.model_validate(doc)

    async def get(self, doc_id: str) -> DocumentResponse:
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return DocumentResponse.model_validate(doc)

    async def list_documents(self, page: int = 1, page_size: int = 20) -> DocumentListResponse:
        skip = (page - 1) * page_size
        docs, total = await self.repo.list_active(skip=skip, limit=page_size)
        return DocumentListResponse(
            items=[DocumentResponse.model_validate(d) for d in docs],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def delete(self, doc_id: str) -> None:
        deleted = await self.repo.soft_delete(doc_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        # Queue vector cleanup
        from app.workers.tasks.ingestion import delete_document_vectors
        delete_document_vectors.delay(doc_id)

    async def reindex(self, doc_id: str) -> DocumentResponse:
        doc = await self.repo.get_by_id(doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        from app.workers.tasks.ingestion import reindex_document
        reindex_document.delay(doc_id)
        return DocumentResponse.model_validate(doc)
