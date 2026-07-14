from fastapi import APIRouter, Depends, Query, UploadFile

from app.core.config import settings
from app.core.dependencies import CurrentUserDep, DbDep
from app.core.rate_limit import rate_limiter
from app.models.user import UserRole
from app.schemas.document import DocumentListResponse, DocumentResponse, ReindexRequest
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


def _is_admin(user) -> bool:
    return user.role == UserRole.admin


@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=202,
    dependencies=[
        Depends(rate_limiter(settings.UPLOAD_RATE_LIMIT_PER_MINUTE, 60, "upload")),
    ],
)
async def upload_document(file: UploadFile, user: CurrentUserDep, db: DbDep):
    """Upload a document. Raw file → S3. Metadata → Supabase. Ingestion dispatched async."""
    service = DocumentService(db)
    return await service.upload(file, user_id=user.id)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    user: CurrentUserDep,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    service = DocumentService(db)
    return await service.list_documents(
        user_id=user.id, is_admin=_is_admin(user), page=page, page_size=page_size
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, user: CurrentUserDep, db: DbDep):
    service = DocumentService(db)
    return await service.get(doc_id, user_id=user.id, is_admin=_is_admin(user))


@router.get("/{doc_id}/download")
async def get_download_url(
    doc_id: str,
    user: CurrentUserDep,
    db: DbDep,
    expires: int = Query(default=3600, ge=60, le=86400, description="URL expiry in seconds"),
):
    """
    Return a presigned S3 URL for direct download of the raw document file.
    The frontend downloads directly from S3 — no proxying through the API.
    """
    service = DocumentService(db)
    url = await service.get_download_url(
        doc_id, user_id=user.id, is_admin=_is_admin(user), expires_seconds=expires
    )
    return {"url": url, "expires_in": expires}


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, user: CurrentUserDep, db: DbDep):
    """Soft-delete metadata in Supabase. S3 file + vectors deleted async via Celery."""
    service = DocumentService(db)
    await service.delete(doc_id, user_id=user.id, is_admin=_is_admin(user))


@router.post("/reindex", response_model=DocumentResponse)
async def reindex_document(body: ReindexRequest, user: CurrentUserDep, db: DbDep):
    """Re-download from S3 and rebuild all vectors. S3 file is preserved."""
    service = DocumentService(db)
    return await service.reindex(body.document_id, user_id=user.id, is_admin=_is_admin(user))
