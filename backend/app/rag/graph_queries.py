"""
Graph explorer data layer — Cypher cho "Giao diện Nâng cao" (đồ thị Neo4j tương tác).

Đây là NƠI DUY NHẤT chứa Cypher của tính năng đồ thị. Tầng render (frontend) và tầng
service KHÔNG biết schema graph — chúng chỉ thấy DTO ổn định:

    node: {id, label, type, group, meta}
    edge: {source, target, rel}

Khi Provision layer (Điều/Khoản/Điểm + VIEN_DAN) chạy thật, chỉ cần sửa Cypher + nhãn
trong file này; service/route/component giữ nguyên.

Trạng thái hiện tại (giai đoạn Chunk):
  • Neo4j chỉ có (:Chunk) + NEXT_CHUNK + REFERENCES (xem ingestion/graph_indexer.py).
  • REFERENCES chỉ nối chunk TRONG CÙNG 1 tài liệu → cấp document KHÔNG có cạnh giữa
    các tài liệu. Cypher cạnh cross-document vẫn viết dạng tổng quát để khi có
    VIEN_DAN cross-doc thì tự lên edge, không phải viết lại.

Bảo mật: mọi truy vấn filter `owner_id` + giới hạn `document_ids` — mirror
`HybridRetriever._graph_search` (rag/retriever.py). owner_id=None = admin/không filter.

Async: các hàm ở đây là SYNC (Neo4j driver đồng bộ). Gọi từ route async PHẢI bọc
`asyncio.to_thread(...)` (xem services/graph_service.py) để không block event loop.

Graceful degradation: Neo4j không sẵn sàng → trả cấu trúc rỗng + log, không raise
(nhất quán với retriever).
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _owner_clause(alias: str, owner_id: str | None) -> str:
    """Fragment filter owner cho 1 alias node. owner_id=None (admin) → không filter."""
    return f"AND {alias}.owner_id = $owner_id" if owner_id is not None else ""


def fetch_overview(document_ids: list[str], owner_id: str | None) -> dict[str, Any]:
    """
    Cấp mặc định — mỗi tài liệu = 1 node.

    Node document gom từ các Chunk cùng document_id (kèm số chunk để hiện cỡ/nhãn).
    Edge = viện dẫn CROSS-DOCUMENT (hiện rỗng ở giai đoạn Chunk; dạng tổng quát).

    Returns {"nodes": [...], "edges": [...]}.
    """
    if not document_ids:
        return {"nodes": [], "edges": []}

    try:
        from app.rag.graph_client import get_neo4j_driver

        driver = get_neo4j_driver()
        with driver.session() as session:
            node_records = session.run(
                f"""
                MATCH (c:Chunk)
                WHERE c.document_id IN $document_ids
                {_owner_clause("c", owner_id)}
                RETURN c.document_id                       AS document_id,
                       head(collect(c.document_name))      AS document_name,
                       count(c)                            AS chunk_count
                """,
                document_ids=document_ids,
                owner_id=owner_id,
            ).data()

            # Cạnh cross-document: viện dẫn từ chunk thuộc doc A sang chunk thuộc doc B
            # (A ≠ B). Giai đoạn Chunk trả rỗng (REFERENCES chỉ nội bộ 1 doc); khi có
            # Provision VIEN_DAN cross-doc thì bổ sung rel vào pattern là đủ.
            edge_records = session.run(
                f"""
                MATCH (a:Chunk)-[:REFERENCES]->(b:Chunk)
                WHERE a.document_id IN $document_ids
                  AND b.document_id IN $document_ids
                  AND a.document_id <> b.document_id
                  {_owner_clause("a", owner_id)}
                  {_owner_clause("b", owner_id)}
                RETURN DISTINCT a.document_id AS source, b.document_id AS target
                """,
                document_ids=document_ids,
                owner_id=owner_id,
            ).data()
    except Exception:
        logger.exception("Neo4j overview query failed — trả đồ thị rỗng (graceful)")
        return {"nodes": [], "edges": []}

    nodes = [
        {
            "id": r["document_id"],
            "label": r["document_name"] or "Tài liệu",
            "type": "document",
            "group": r["document_id"],
            "meta": {"chunk_count": r["chunk_count"]},
        }
        for r in node_records
    ]
    edges = [
        {"source": r["source"], "target": r["target"], "rel": "REFERENCES"} for r in edge_records
    ]
    return {"nodes": nodes, "edges": edges}
