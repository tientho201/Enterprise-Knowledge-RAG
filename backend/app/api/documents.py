from fastapi import APIRouter, Query, UploadFile

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.schemas.document import DocumentListResponse, DocumentResponse, ReindexRequest
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(file: UploadFile, user_id: CurrentUserIdDep, db: DbDep):
    service = DocumentService(db)
    return await service.upload(file, user_id=user_id)


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    _user_id: CurrentUserIdDep,
    db: DbDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    service = DocumentService(db)
    return await service.list_documents(page=page, page_size=page_size)


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, _user_id: CurrentUserIdDep, db: DbDep):
    service = DocumentService(db)
    return await service.get(doc_id)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, user_id: CurrentUserIdDep, db: DbDep):
    service = DocumentService(db)
    await service.delete(doc_id, user_id=user_id)


@router.post("/reindex", response_model=DocumentResponse)
async def reindex_document(body: ReindexRequest, user_id: CurrentUserIdDep, db: DbDep):
    service = DocumentService(db)
    return await service.reindex(body.document_id, user_id=user_id)
