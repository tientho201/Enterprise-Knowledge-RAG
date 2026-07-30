"""
Graph-augmented retrieval qua Provision layer (citation graph) — chạy CHỈ khi
chế độ tra cứu "Nâng cao" (search_mode="advanced", đã qua gate `core/plan_gate.py`).

Đây KHÔNG phải multi-hop agentic loop (agent tự đánh giá đủ ngữ cảnh chưa rồi lặp
lại nhiều vòng) — đó là phase sau. Luồng ở đây chạy đúng 1 vòng:

  1. Map chunk neo (kết quả dense search có sẵn) -> Provision qua HAS_CHUNK.
  2. Từ Provision neo, traverse VIEN_DAN 1..CITATION_GRAPH_MAX_HOPS hop (2 chiều —
     cả "Điều này viện dẫn đâu" lẫn "ai viện dẫn Điều này") lấy Provision liên quan.
  3. Từ Provision neo + liên quan (và LegalDocument của chính văn bản chứa chúng,
     cho phần viện dẫn ở đoạn mở đầu/preamble không nằm trong Provision nào), traverse
     VIEN_DAN_VAN_BAN 1 hop lấy LegalDocument được viện dẫn (nhóm chỉ-có-mã-văn-bản).

Cơ chế gợi ý (đã chốt thiết kế, xem task):
  - Provision thật (is_placeholder=false) thuộc 1 document nằm trong *document_ids*
    (đã gắn vào hội thoại) -> gộp vào context. document_ids=None (user không giới
    hạn tài liệu) -> coi mọi thứ là trong phạm vi.
  - Provision/LegalDocument thật nhưng thuộc document CHƯA gắn vào hội thoại này
    (có trong thư viện owner, ở nơi khác) -> suggested_documents (in_library=True),
    KHÔNG lôi vào context.
  - is_placeholder=true (văn bản đích chưa từng được ingest bởi owner này) ->
    suggested_documents (in_library=False).
  - LegalDocument luôn luôn suggestion-only — node này không có nội dung cấp Điều
    (content=null theo thiết kế graph_indexer.py) nên không có gì để đưa vào context.

Bảo mật: mọi Cypher filter owner_id (mirror HybridRetriever._graph_search). Namespace
legal_address đã prefix owner_{owner_id} nên graph tự nhiên tách theo owner; filter
owner_id ở đây là defense-in-depth, không phải cơ chế cách ly duy nhất.

Graceful degradation: lỗi Neo4j (mất kết nối, timeout...) -> trả kết quả rỗng, không
raise (nhất quán với HybridRetriever._graph_search / rag/graph_queries.py).

Sync (Neo4j driver đồng bộ) — caller (agents/retriever.py::retriever_node) PHẢI bọc
asyncio.to_thread(...), không được gọi trực tiếp trong route/node async.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.ingestion.graph_indexer import build_document_address
from app.rag.retriever import RetrievedChunk

logger = logging.getLogger(__name__)


@dataclass
class CitationGraphResult:
    context_chunks: list[RetrievedChunk] = field(default_factory=list)
    citation_graph_path: list[dict] = field(default_factory=list)
    suggested_documents: list[dict] = field(default_factory=list)


def _owner_clause(alias: str, owner_id: str | None) -> str:
    """Fragment filter owner cho 1 alias node. owner_id=None (admin) → không filter."""
    return f"AND {alias}.owner_id = $owner_id" if owner_id is not None else ""


def _in_scope(document_id: str | None, document_ids: list[str] | None) -> bool:
    """document_ids=None → user không giới hạn tài liệu → coi mọi thứ trong phạm vi.
    document_id=None (không resolve được) → luôn ngoài phạm vi (không có gì để gộp)."""
    if document_id is None:
        return False
    return document_ids is None or document_id in document_ids


# ── Bước 1: map chunk neo (dense search) -> Provision ────────────────────────


def _anchor_provisions(session: Any, seed_chunk_ids: list[str], owner_id: str | None) -> list[dict]:
    """Provision chứa 1 trong các seed_chunk_ids (kết quả dense search) qua HAS_CHUNK.

    seed_chunk là chunk_id ĐÃ owner/document-scoped bởi HybridRetriever._dense_search
    trước khi tới đây — chunk_id chính là citation-safe (trùng Postgres chunks.id, xem
    workers/tasks/ingestion.py::_make_chunk_id)."""
    if not seed_chunk_ids:
        return []
    result = session.run(
        f"""
        UNWIND $seed_ids AS cid
        MATCH (p:Provision)-[:HAS_CHUNK]->(seed_chunk:Chunk {{chunk_id: cid}})
        WHERE p.is_placeholder = false
        {_owner_clause("p", owner_id)}
        RETURN DISTINCT
            p.legal_address  AS legal_address,
            p.document_code  AS document_code,
            p.content        AS content,
            seed_chunk.chunk_id       AS chunk_id,
            seed_chunk.document_id    AS document_id,
            seed_chunk.document_name  AS document_name
        """,
        seed_ids=seed_chunk_ids,
        owner_id=owner_id,
    )
    return result.data()


# ── Bước 2: traverse VIEN_DAN 1..N hop ───────────────────────────────────────


def _traverse_related_provisions(
    session: Any,
    anchor_addrs: list[str],
    owner_id: str | None,
    max_hops: int,
    limit: int,
) -> list[dict]:
    """Provision liên quan qua VIEN_DAN (2 chiều — undirected, mirror cách
    HybridRetriever._graph_search traverse NEXT_CHUNK|REFERENCES) từ mỗi anchor.

    max_hops chèn trực tiếp vào range Cypher (`*1..{max_hops}`) — PHẢI là int từ
    settings server-side, KHÔNG BAO GIỜ nhận trực tiếp từ input người dùng."""
    if not anchor_addrs:
        return []
    max_hops = int(max_hops)
    result = session.run(
        f"""
        UNWIND $anchors AS anchor_addr
        MATCH (a:Provision {{legal_address: anchor_addr}})
        MATCH path = (a)-[:VIEN_DAN*1..{max_hops}]-(related:Provision)
        WHERE related.legal_address <> anchor_addr
        {_owner_clause("related", owner_id)}
        OPTIONAL MATCH (related)-[:HAS_CHUNK]->(rc:Chunk)
        WITH anchor_addr, related, min(length(path)) AS hops,
             collect(DISTINCT rc.chunk_id)[0]      AS chunk_id,
             collect(DISTINCT rc.document_id)[0]   AS document_id,
             collect(DISTINCT rc.document_name)[0] AS document_name
        RETURN
            anchor_addr,
            related.legal_address  AS legal_address,
            related.document_code  AS document_code,
            related.content        AS content,
            related.is_placeholder AS is_placeholder,
            hops, chunk_id, document_id, document_name
        ORDER BY hops ASC
        LIMIT $limit
        """,
        anchors=anchor_addrs,
        owner_id=owner_id,
        limit=limit,
    )
    return result.data()


# ── Bước 3: LegalDocument được viện dẫn (nhóm chỉ-có-mã-văn-bản) ─────────────


def _traverse_legal_documents(
    session: Any,
    provision_addrs: list[str],
    own_doc_addrs: list[str],
    owner_id: str | None,
) -> list[dict]:
    """LegalDocument đích của VIEN_DAN_VAN_BAN, xuất phát từ:
      - Provision (viện dẫn nằm trong 1 Điều/Khoản/Điểm đã parse được), và
      - LegalDocument của chính văn bản chứa Provision đó (viện dẫn ở phần mở đầu/
        preamble, không nằm trong Provision nào — xem graph_indexer.py).

    Resolve luôn document_id (Postgres) của đích nếu đã có Provision thật nào cùng
    document_code+owner được HAS_CHUNK tới 1 Chunk — dùng để phân biệt "đã có trong
    thư viện owner" (dù chưa gắn vào hội thoại này) với "chưa có trong thư viện"."""
    owner_clause_d = _owner_clause("d", owner_id)
    rows: list[dict] = []

    if provision_addrs:
        result = session.run(
            f"""
            UNWIND $addrs AS src
            MATCH (p:Provision {{legal_address: src}})-[:VIEN_DAN_VAN_BAN]->(d:LegalDocument)
            WHERE true {owner_clause_d}
            OPTIONAL MATCH (dp:Provision {{document_code: d.document_code}})-[:HAS_CHUNK]->(dc:Chunk)
            WHERE dp.owner_id = d.owner_id
            WITH src, d, collect(DISTINCT dc.document_id)[0]   AS document_id,
                         collect(DISTINCT dc.document_name)[0] AS document_name
            RETURN DISTINCT
                src AS source_addr,
                d.legal_address  AS legal_address,
                d.document_code  AS document_code,
                d.name           AS name,
                d.is_placeholder AS is_placeholder,
                document_id, document_name
            """,
            addrs=provision_addrs,
            owner_id=owner_id,
        )
        rows.extend(result.data())

    if own_doc_addrs:
        result = session.run(
            f"""
            UNWIND $addrs AS src
            MATCH (s:LegalDocument {{legal_address: src}})-[:VIEN_DAN_VAN_BAN]->(d:LegalDocument)
            WHERE true {owner_clause_d}
            OPTIONAL MATCH (dp:Provision {{document_code: d.document_code}})-[:HAS_CHUNK]->(dc:Chunk)
            WHERE dp.owner_id = d.owner_id
            WITH src, d, collect(DISTINCT dc.document_id)[0]   AS document_id,
                         collect(DISTINCT dc.document_name)[0] AS document_name
            RETURN DISTINCT
                src AS source_addr,
                d.legal_address  AS legal_address,
                d.document_code  AS document_code,
                d.name           AS name,
                d.is_placeholder AS is_placeholder,
                document_id, document_name
            """,
            addrs=own_doc_addrs,
            owner_id=owner_id,
        )
        rows.extend(result.data())

    return rows


# ── Orchestration ─────────────────────────────────────────────────────────────


def graph_augmented_search(
    seed_chunk_ids: list[str],
    document_ids: list[str] | None,
    owner_id: str | None,
) -> CitationGraphResult:
    """Điểm vào duy nhất — gọi từ agents/retriever.py qua asyncio.to_thread.

    seed_chunk_ids: chunk_id của kết quả dense search (đã owner/document-scoped).
    document_ids:   tài liệu đã gắn vào hội thoại hiện tại (None = không giới hạn).
    owner_id:       data isolation, mirror HybridRetriever (None = admin).
    """
    if not seed_chunk_ids:
        return CitationGraphResult()

    try:
        from app.rag.graph_client import get_neo4j_driver

        driver = get_neo4j_driver()
        max_hops = settings.CITATION_GRAPH_MAX_HOPS
        limit = settings.CITATION_GRAPH_MAX_RELATED

        with driver.session() as session:
            anchor_rows = _anchor_provisions(session, seed_chunk_ids, owner_id)
            if not anchor_rows:
                return CitationGraphResult()

            anchors_by_addr: dict[str, dict] = {}
            for row in anchor_rows:
                anchors_by_addr.setdefault(row["legal_address"], row)
            anchor_addrs = list(anchors_by_addr.keys())

            related_rows = _traverse_related_provisions(
                session, anchor_addrs, owner_id, max_hops, limit
            )
            related_by_addr: dict[str, dict] = {}
            for row in related_rows:
                addr = row["legal_address"]
                current = related_by_addr.get(addr)
                if current is None or row["hops"] < current["hops"]:
                    related_by_addr[addr] = row

            real_related_addrs = [
                addr for addr, row in related_by_addr.items() if not row["is_placeholder"]
            ]
            doc_codes = {row["document_code"] for row in anchors_by_addr.values()}
            doc_codes |= {row["document_code"] for row in related_by_addr.values()}
            own_doc_addrs = [build_document_address(owner_id, code) for code in doc_codes]

            legal_doc_rows = _traverse_legal_documents(
                session, anchor_addrs + real_related_addrs, own_doc_addrs, owner_id
            )
    except Exception:  # Neo4j unavailable / query error → graceful degradation
        logger.exception("Citation graph traversal failed — trả kết quả rỗng (graceful)")
        return CitationGraphResult()

    return _classify(anchors_by_addr, related_by_addr, legal_doc_rows, document_ids)


def _classify(
    anchors_by_addr: dict[str, dict],
    related_by_addr: dict[str, dict],
    legal_doc_rows: list[dict],
    document_ids: list[str] | None,
) -> CitationGraphResult:
    """Phân loại kết quả traversal thành context (gộp vào retrieval) và
    suggested_documents (gợi ý, KHÔNG vào context) — xem quy tắc ở module docstring."""
    context_chunks: list[RetrievedChunk] = []
    citation_graph_path: list[dict] = []
    suggested_by_code: dict[str, dict] = {}

    def add_suggestion(
        document_code: str,
        document_id: str | None,
        name: str | None,
        in_library: bool,
        cited_from: str,
    ) -> None:
        if document_code in suggested_by_code:
            return
        suggested_by_code[document_code] = {
            "document_code": document_code,
            "document_id": document_id,
            "name": name,
            "in_library": in_library,
            "cited_from": cited_from,
        }

    # Anchor: Provision khớp trực tiếp dense search → luôn trong context (chính nó
    # đã owner/document-scoped từ _dense_search trước khi tới traversal này).
    for row in anchors_by_addr.values():
        context_chunks.append(
            RetrievedChunk(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"] or "",
                document_name=row["document_name"] or "",
                content=row["content"] or "",
                score=1.0,
                chunk_index=0,
            )
        )

    for addr, row in related_by_addr.items():
        anchor_addr = row["anchor_addr"]
        hops = row["hops"]

        if row["is_placeholder"]:
            citation_graph_path.append(
                {
                    "from_address": anchor_addr,
                    "to_address": addr,
                    "relation": "VIEN_DAN",
                    "hops": hops,
                    "in_context": False,
                }
            )
            add_suggestion(row["document_code"], None, None, False, anchor_addr)
            continue

        in_scope = _in_scope(row["document_id"], document_ids)
        citation_graph_path.append(
            {
                "from_address": anchor_addr,
                "to_address": addr,
                "relation": "VIEN_DAN",
                "hops": hops,
                "in_context": in_scope,
            }
        )
        if in_scope:
            context_chunks.append(
                RetrievedChunk(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"] or "",
                    document_name=row["document_name"] or "",
                    content=row["content"] or "",
                    score=0.5**hops,
                    chunk_index=0,
                )
            )
        else:
            add_suggestion(
                row["document_code"], row["document_id"], row["document_name"], True, anchor_addr
            )

    for row in legal_doc_rows:
        addr = row["legal_address"]
        source_addr = row["source_addr"]
        citation_graph_path.append(
            {
                "from_address": source_addr,
                "to_address": addr,
                "relation": "VIEN_DAN_VAN_BAN",
                "hops": 1,
                "in_context": False,  # LegalDocument không có nội dung cấp Điều
            }
        )
        if row["is_placeholder"]:
            add_suggestion(row["document_code"], None, None, False, source_addr)
            continue

        resolved_id = row.get("document_id")
        if resolved_id and _in_scope(resolved_id, document_ids):
            continue  # đã gắn vào hội thoại này — không cần gợi ý
        add_suggestion(
            row["document_code"], resolved_id, row.get("name"), bool(resolved_id), source_addr
        )

    return CitationGraphResult(
        context_chunks=context_chunks,
        citation_graph_path=citation_graph_path,
        suggested_documents=list(suggested_by_code.values()),
    )
