"""
Graph indexer: persists document chunks and legal cross-reference edges into Neo4j.

Graph schema
────────────
Nodes
  (:Chunk {chunk_id, document_id, document_name, content, chunk_index})

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
) -> None:
    """
    Upsert chunk nodes and edges for *document_id* into Neo4j.

    Idempotent — uses MERGE, safe to call on re-index.
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
                 c.chunk_index   = ch.chunk_index
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
