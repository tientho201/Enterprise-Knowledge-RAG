"""
Graph explorer API — đồ thị Neo4j tương tác cho "Giao diện Nâng cao".

Mọi route qua `require_advanced_access` (gate gói Pro) — user free gọi thẳng vẫn 403.
Client chỉ gửi tham số (conversation_id / document_id / query); backend tự dựng Cypher
(chống injection). Xem services/graph_service.py + rag/graph_queries.py.
"""

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import CurrentUserDep, DbDep
from app.core.plan_gate import require_advanced_access
from app.schemas.graph import GraphExpandResponse, GraphOverviewResponse
from app.services.graph_service import GraphService

router = APIRouter(
    prefix="/graph",
    tags=["graph"],
    dependencies=[Depends(require_advanced_access)],
)


@router.get("/overview", response_model=GraphOverviewResponse)
async def overview(
    user: CurrentUserDep,
    db: DbDep,
    conversation_id: str = Query(..., alias="conversation_id"),
):
    """Endpoint A — cấu trúc đồ thị cấp tài liệu cho 1 hội thoại (nạp 1 lần ở client)."""
    return await GraphService(db).overview(user, conversation_id)


@router.get("/expand", response_model=GraphExpandResponse)
async def expand(
    user: CurrentUserDep,
    db: DbDep,
    conversation_id: str = Query(..., alias="conversation_id"),
    document_id: str = Query(..., alias="document_id"),
):
    """Endpoint A — bung 1 tài liệu → chunk của nó (lazy, trần GRAPH_MAX_NODES node)."""
    return await GraphService(db).expand(user, conversation_id, document_id)
