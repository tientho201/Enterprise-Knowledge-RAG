"""
Graph indexer: persists document chunks and legal cross-reference edges into Neo4j.

Graph schema
────────────
Nodes
  (:Chunk {chunk_id, document_id, document_name, content, chunk_index, owner_id})

Relationships
  (a:Chunk)-[:NEXT_CHUNK]->(b:Chunk)    — consecutive chunks in the same document
  (a:Chunk)-[:REFERENCES]->(b:Chunk)    — a's text explicitly mentions an article
                                          that b belongs to (within same document)

Legal cross-reference patterns detected (Vietnamese)
  • "Điều 5", "điều 10"
  • "khoản 2 Điều 5"
  • "điểm a khoản 1 Điều 3"
  • "Chương II", "chương 3"
  • "Mục 4"
  • "Nghị định số 12/2024/NĐ-CP" (referenced decrees — future: cross-document)
"""

import logging
import re
from dataclasses import dataclass

from neo4j import Driver

logger = logging.getLogger(__name__)

# ── Vietnamese legal reference patterns ──────────────────────────────────────
# Captures the article number from expressions like:
#   "Điều 5", "điều 10", "khoản 2 Điều 5", "điểm a khoản 1 Điều 3"
_ARTICLE_PATTERN = re.compile(
    r"(?:kho\u1ea3n\s+\d+\s+)?(?:\u0111i\u1ec3m\s+[a-z\u0111]\s+)?[Đ\u0111]i\u1ec1u\s+(\d+)",
    re.UNICODE,
)

# Matches "Chương X" / "chương 10"
_CHAPTER_PATTERN = re.compile(
    r"[Cc]h\u01b0\u01a1ng\s+([IVXLCDM\d]+)",
    re.UNICODE,
)


@dataclass
class ChunkRecord:
    chunk_id: str
    content: str
    chunk_index: int


def _extract_article_numbers(text: str) -> set[str]:
    """Return all article numbers referenced in *text*."""
    return {m.group(1) for m in _ARTICLE_PATTERN.finditer(text)}


def _build_article_map(chunks: list[ChunkRecord]) -> dict[str, list[str]]:
    """
    Build article_number → [chunk_ids] mapping.

    Heuristic: a chunk "belongs to" article N if its text starts with a heading
    matching "Điều N" or contains it near the start (first 120 chars).
    """
    article_map: dict[str, list[str]] = {}
    for chunk in chunks:
        preview = chunk.content[:120]
        for art_num in _extract_article_numbers(preview):
            article_map.setdefault(art_num, []).append(chunk.chunk_id)
    return article_map


# ── Public API ────────────────────────────────────────────────────────────────


def index_chunks_to_graph(
    driver: Driver,
    document_id: str,
    document_name: str,
    chunks: list[ChunkRecord],
    owner_id: str | None = None,
) -> None:
    """
    Upsert chunk nodes and edges for *document_id* into Neo4j.

    Idempotent — uses MERGE, safe to call on re-index.

    owner_id được ghi lên node để retriever `_graph_search` filter theo chủ sở hữu
    (data isolation). None = doc legacy/không có owner.
    """
    if not chunks:
        return

    chunk_params = [
        {
            "chunk_id": c.chunk_id,
            "document_id": document_id,
            "document_name": document_name,
            "content": c.content,
            "chunk_index": c.chunk_index,
            "owner_id": owner_id,
        }
        for c in chunks
    ]

    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_index)

    # ── 1. Upsert Chunk nodes ─────────────────────────────────────────────────
    with driver.session() as session:
        session.run(
            """
            UNWIND $chunks AS ch
            MERGE (c:Chunk {chunk_id: ch.chunk_id})
            SET  c.document_id   = ch.document_id,
                 c.document_name = ch.document_name,
                 c.content       = ch.content,
                 c.chunk_index   = ch.chunk_index,
                 c.owner_id      = ch.owner_id
            """,
            chunks=chunk_params,
        )

    # ── 2. NEXT_CHUNK sequential edges ────────────────────────────────────────
    if len(sorted_chunks) > 1:
        seq_pairs = [
            {"from_id": sorted_chunks[i].chunk_id, "to_id": sorted_chunks[i + 1].chunk_id}
            for i in range(len(sorted_chunks) - 1)
        ]
        with driver.session() as session:
            session.run(
                """
                UNWIND $pairs AS p
                MATCH (a:Chunk {chunk_id: p.from_id})
                MATCH (b:Chunk {chunk_id: p.to_id})
                MERGE (a)-[:NEXT_CHUNK]->(b)
                """,
                pairs=seq_pairs,
            )

    # ── 3. REFERENCES edges from cross-reference parsing ─────────────────────
    article_map = _build_article_map(sorted_chunks)
    ref_pairs: list[dict] = []

    for chunk in sorted_chunks:
        mentioned = _extract_article_numbers(chunk.content)
        for art_num in mentioned:
            for target_id in article_map.get(art_num, []):
                if target_id != chunk.chunk_id:
                    ref_pairs.append({"from_id": chunk.chunk_id, "to_id": target_id})

    if ref_pairs:
        with driver.session() as session:
            session.run(
                """
                UNWIND $pairs AS p
                MATCH (a:Chunk {chunk_id: p.from_id})
                MATCH (b:Chunk {chunk_id: p.to_id})
                MERGE (a)-[:REFERENCES]->(b)
                """,
                pairs=ref_pairs,
            )

    logger.info(
        "Neo4j indexed: document=%s  chunks=%d  ref_edges=%d",
        document_id,
        len(chunks),
        len(ref_pairs),
    )


def delete_document_from_graph(driver: Driver, document_id: str) -> None:
    """Detach-delete all Chunk nodes belonging to *document_id*."""
    with driver.session() as session:
        session.run(
            "MATCH (c:Chunk {document_id: $document_id}) DETACH DELETE c",
            document_id=document_id,
        )
    logger.info("Neo4j nodes deleted for document=%s", document_id)


# ── Provision layer (citation graph — Phase 1: viện dẫn nội bộ) ─────────────
#
# Node
#   (:Provision {legal_address, owner_id, document_code, dieu, khoan, diem,
#                content, is_placeholder})
#
# Relationships
#   (:Provision)-[:HAS_CHUNK]->(:Chunk)     — Provision trải/chứa 1 phần nội
#                                              dung của Chunk đó (map theo giao
#                                              vùng ký tự, xem ingestion.py)
#   (:Provision)-[:VIEN_DAN]->(:Provision)  — viện dẫn pháp lý
#
# legal_address là khóa MERGE tất định:
#   owner_{owner_id}:{document_code}:DIEU_{n}[:KHOAN_{m}[:DIEM_{x}]]
# Không dùng document_id nội bộ để định danh — placeholder (phase 2) được tạo
# TRƯỚC KHI văn bản đích được upload, lúc đó chưa có document_id.


@dataclass
class ProvisionRecord:
    dieu: int
    khoan: int | None
    diem: str | None
    content: str


def build_legal_address(
    owner_id: str | None,
    document_code: str,
    dieu: int,
    khoan: int | None = None,
    diem: str | None = None,
) -> str:
    """
    Địa chỉ pháp lý tất định — cùng (owner_id, document_code, dieu, khoan, diem)
    luôn ra cùng chuỗi, qua mọi lần ingest/reindex (giống chunk_id ở ingestion.py).

    TODO (kho tài liệu chung — chưa build, chỉ ghi chỗ đặt): khi có kho văn bản quy
    phạm pháp luật công khai (do admin kiểm duyệt), namespace "owner_{owner_id}"
    sẽ cần thêm 1 nhánh "public:{document_code}:DIEU_{n}..." song song (không thay
    owner_id bằng None — None đã có nghĩa khác, "admin/không filter", ở nơi khác
    trong codebase). Chỗ sửa khi làm: hàm này thêm tham số is_public; nơi gọi
    (index_provisions_to_graph, ingestion.py) truyền is_public dựa trên nguồn tài
    liệu; retriever traverse filter theo (owner_id = $owner OR is_public = true).
    """
    parts = [f"owner_{owner_id}", document_code, f"DIEU_{dieu}"]
    if khoan is not None:
        parts.append(f"KHOAN_{khoan}")
        if diem is not None:
            parts.append(f"DIEM_{diem}")
    return ":".join(parts)


def index_provisions_to_graph(
    driver: Driver,
    owner_id: str | None,
    document_code: str,
    provisions: list[ProvisionRecord],
    chunk_links: list[tuple[tuple[int, int | None, str | None], str]],
    citations: list[tuple[tuple[int, int | None, str | None], tuple[int, int | None, str | None]]],
) -> None:
    """
    Upsert Provision nodes + HAS_CHUNK + VIEN_DAN edges cho 1 văn bản.

    Idempotent — toàn bộ dùng MERGE theo legal_address, an toàn gọi lại khi
    retry/reindex (không nhân đôi node/edge).

    chunk_links: [((dieu, khoan, diem), chunk_id), ...] — cạnh Provision -> Chunk.
    citations:   [((dieu, khoan, diem)_nguồn, (dieu, khoan, diem)_đích), ...].

    Phase 1 CHƯA tạo placeholder: nếu tầng gọi (ingestion.py) truyền vào 1 citation
    có đích không nằm trong *provisions* của chính văn bản này, đó là lỗi gọi sai
    (structural_parser.extract_citations đã tự lọc trước) — hàm này giả định mọi
    (dieu, khoan, diem) xuất hiện trong chunk_links/citations đều có mặt trong
    *provisions*.

    TODO (phase sau): thêm backing record Postgres cho audit/hiển thị, map 1-1
    theo legal_address — legal_address được thiết kế làm khóa sạch ngay từ đầu
    để việc này không cần refactor gì ở đây.
    """
    if not provisions:
        return

    def addr(key: tuple[int, int | None, str | None]) -> str:
        dieu, khoan, diem = key
        return build_legal_address(owner_id, document_code, dieu, khoan, diem)

    provision_params = [
        {
            "legal_address": build_legal_address(owner_id, document_code, p.dieu, p.khoan, p.diem),
            "owner_id": owner_id,
            "document_code": document_code,
            "dieu": p.dieu,
            "khoan": p.khoan,
            "diem": p.diem,
            "content": p.content,
        }
        for p in provisions
    ]

    with driver.session() as session:
        session.run(
            """
            UNWIND $provisions AS pr
            MERGE (p:Provision {legal_address: pr.legal_address})
            SET  p.owner_id       = pr.owner_id,
                 p.document_code  = pr.document_code,
                 p.dieu           = pr.dieu,
                 p.khoan          = pr.khoan,
                 p.diem           = pr.diem,
                 p.content        = pr.content,
                 p.is_placeholder = false
            """,
            provisions=provision_params,
        )

    if chunk_links:
        link_params = [
            {"legal_address": addr(key), "chunk_id": chunk_id} for key, chunk_id in chunk_links
        ]
        with driver.session() as session:
            session.run(
                """
                UNWIND $links AS l
                MATCH (p:Provision {legal_address: l.legal_address})
                MATCH (c:Chunk {chunk_id: l.chunk_id})
                MERGE (p)-[:HAS_CHUNK]->(c)
                """,
                links=link_params,
            )

    if citations:
        cite_params = [{"from_addr": addr(src), "to_addr": addr(dst)} for src, dst in citations]
        with driver.session() as session:
            session.run(
                """
                UNWIND $cites AS ci
                MATCH (a:Provision {legal_address: ci.from_addr})
                MATCH (b:Provision {legal_address: ci.to_addr})
                MERGE (a)-[:VIEN_DAN]->(b)
                """,
                cites=cite_params,
            )

    logger.info(
        "Neo4j Provision indexed: document_code=%s provisions=%d chunk_links=%d citations=%d",
        document_code,
        len(provisions),
        len(chunk_links),
        len(citations),
    )
