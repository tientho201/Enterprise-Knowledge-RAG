"""Pydantic schemas cho graph explorer (Giao diện Nâng cao).

DTO ổn định giữa backend và frontend — độc lập với schema Neo4j (xem rag/graph_queries.py).
Alias camelCase để khớp convention client (giống schemas/chat.py).
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    label: str
    # "document" ở cấp mặc định; "chunk" khi bung 1 tài liệu (sau này: "provision").
    type: Literal["document", "chunk", "provision"]
    # Nhóm theo document_id — cùng group = cùng tài liệu (tô màu/kéo cụm ở client).
    group: str
    meta: dict[str, Any] = {}


class GraphEdge(BaseModel):
    source: str
    target: str
    # Loại quan hệ: REFERENCES / NEXT_CHUNK (sau này: VIEN_DAN).
    rel: str


class GraphOverviewResponse(BaseModel):
    """Endpoint A (cấp tài liệu) — nạp 1 lần, giữ ở client state."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphExpandResponse(BaseModel):
    """Endpoint A (bung 1 tài liệu → chunk của nó)."""

    document_id: str = Field(alias="documentId")
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # Trần cứng backend (GRAPH_MAX_NODES). truncated=True → client báo "hiển thị
    # returned/total node" + gợi ý bỏ bớt tài liệu.
    truncated: bool = False
    total: int = 0
    returned: int = 0

    model_config = {"populate_by_name": True}


class GraphHighlightRequest(BaseModel):
    """Endpoint B — CHỈ trả ID node trúng, KHÔNG trả lại graph."""

    conversation_id: str = Field(alias="conversationId")
    query: str

    model_config = {"populate_by_name": True}


class GraphHighlightResponse(BaseModel):
    # chunk_id trúng truy vấn + document_id chứa chúng. Client đổi màu/opacity của
    # graph có sẵn (cạnh sáng = 2 đầu đều trúng, suy ở client).
    node_ids: list[str] = Field(serialization_alias="nodeIds")
