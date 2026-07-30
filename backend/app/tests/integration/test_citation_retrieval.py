"""
Integration test — graph-augmented retrieval (rag/citation_retriever.py) qua Provision
layer, cho chế độ tra cứu "Nâng cao" (search_mode="advanced").

Cùng cách ly Neo4j LOCAL như app/tests/integration/test_provision_graph.py (KHÔNG bao
giờ chạm Neo4j Aura production) — tự SKIP nếu không kết nối được.

`graph_augmented_search()` tự import `app.rag.graph_client.get_neo4j_driver` bên trong
hàm (lazy import) nên monkeypatch thẳng module attribute đó trỏ về driver test local.

Không dựng lại pipeline ingest đầy đủ (Qdrant/Celery không cần cho test này) — chỉ mô
phỏng đúng phần ghi Neo4j (Chunk + Provision + HAS_CHUNK + VIEN_DAN + LegalDocument)
mà graph_augmented_search đọc, với chunk_id/document_id tự chọn (không cần khớp format
thật của _make_chunk_id — test này không kiểm tra format chunk_id).
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from neo4j import Driver, GraphDatabase

from app.ingestion.chunker import DocumentChunker
from app.ingestion.graph_indexer import (
    ChunkRecord,
    ProvisionRecord,
    index_chunks_to_graph,
    index_external_placeholders_to_graph,
    index_legal_document_to_graph,
    index_provisions_to_graph,
)
from app.ingestion.structural_parser import (
    extract_citations,
    extract_document_code,
    extract_external_citations,
    parse_provisions,
)
from app.rag.citation_retriever import graph_augmented_search
from app.rag.graph_client import ensure_graph_schema

pytestmark = pytest.mark.neo4j

_TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
_TEST_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "neo4j_password")

# Văn bản A — viện dẫn ngoại tới B (Điều 5, Nghị định 88/2019/NĐ-CP).
DOC_A_TEXT = """Nghị định số 99/2024/NĐ-CP quy định về bảo vệ dữ liệu cá nhân

Điều 1. Phạm vi điều chỉnh
1. Việc xử lý vi phạm được thực hiện theo quy định tại Điều 5 Nghị định số 88/2019/NĐ-CP.
"""

# Văn bản B — được A viện dẫn.
DOC_B_TEXT = """Nghị định số 88/2019/NĐ-CP quy định về xử lý vi phạm

Điều 5. Nguyên tắc xử lý dữ liệu
1. Tổ chức vi phạm sẽ bị xử phạt hành chính theo quy định của pháp luật.
"""


@pytest.fixture
def neo4j_driver() -> Iterator[Driver]:
    driver = GraphDatabase.driver(_TEST_URI, auth=(_TEST_USER, _TEST_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        driver.close()
        pytest.skip(f"Neo4j local không sẵn sàng tại {_TEST_URI}: {exc}")
    ensure_graph_schema(driver)
    yield driver
    driver.close()


@pytest.fixture
def owner_id() -> str:
    return f"test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def patch_neo4j_driver(monkeypatch, neo4j_driver: Driver):
    """graph_augmented_search lazy-import get_neo4j_driver từ app.rag.graph_client —
    trỏ về driver test local thay vì driver production (Aura) mà settings.NEO4J_URI
    trỏ tới (mirror lý do KHÔNG dùng get_neo4j_driver() thẳng, xem test_provision_graph.py)."""
    monkeypatch.setattr("app.rag.graph_client.get_neo4j_driver", lambda: neo4j_driver)


@pytest.fixture
def cleanup_citation_graph(neo4j_driver: Driver, owner_id: str) -> Iterator[None]:
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (p:Provision {owner_id: $o}) DETACH DELETE p", o=owner_id)
        session.run("MATCH (d:LegalDocument {owner_id: $o}) DETACH DELETE d", o=owner_id)
        session.run(
            "MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH $prefix DETACH DELETE c",
            prefix=f"{owner_id}-",
        )


def _ingest(
    driver: Driver, owner_id: str, text: str, document_id: str, document_name: str
) -> tuple[str, list[str]]:
    """Ghi Chunk + Provision + HAS_CHUNK + VIEN_DAN(_VAN_BAN) cho 1 văn bản luật —
    mirror bước 10a/10b/10c của ingest_document (workers/tasks/ingestion.py), đủ dữ
    liệu cho graph_augmented_search đọc. Trả về (document_code, chunk_ids)."""
    chunker = DocumentChunker(chunk_size=300, chunk_overlap=50)
    chunks = chunker.chunk(
        text, metadata={"document_id": document_id, "document_name": document_name}
    )

    chunk_ids = [f"{owner_id}-{document_id}-chunk-{c.chunk_index}" for c in chunks]
    chunk_records = [
        ChunkRecord(chunk_id=cid, content=c.content, chunk_index=c.chunk_index)
        for cid, c in zip(chunk_ids, chunks, strict=True)
    ]
    index_chunks_to_graph(driver, document_id, document_name, chunk_records, owner_id=owner_id)

    provisions = parse_provisions(text)
    document_code = extract_document_code(text)
    assert document_code is not None
    citations = extract_citations(text, provisions)
    external_citations = extract_external_citations(text, provisions, document_code)

    chunk_links: list[tuple[tuple[int, int | None, str | None], str]] = []
    for p in provisions:
        for cid, c in zip(chunk_ids, chunks, strict=True):
            c_start, c_end = c.char_start, c.char_start + len(c.content)
            if c_start < p.char_end and c_end > p.char_start:
                chunk_links.append(((p.key.dieu, p.key.khoan, p.key.diem), cid))

    provision_records = [
        ProvisionRecord(dieu=p.key.dieu, khoan=p.key.khoan, diem=p.key.diem, content=p.content)
        for p in provisions
    ]
    citation_pairs = [
        (
            (c.source.dieu, c.source.khoan, c.source.diem),
            (c.target.dieu, c.target.khoan, c.target.diem),
        )
        for c in citations
    ]
    index_provisions_to_graph(
        driver, owner_id, document_code, provision_records, chunk_links, citation_pairs
    )
    index_legal_document_to_graph(driver, owner_id, document_code, document_name)

    resolvable_external = [
        (
            (c.source.dieu, c.source.khoan, c.source.diem) if c.source else None,
            c.document_code,
            c.dieu,
            c.khoan,
            c.diem,
        )
        for c in external_citations
        if c.dieu is not None
    ]
    if resolvable_external:
        index_external_placeholders_to_graph(driver, owner_id, document_code, resolvable_external)

    return document_code, chunk_ids


def test_both_documents_attached_pulls_cited_provision_into_context(
    neo4j_driver: Driver, owner_id: str, patch_neo4j_driver, cleanup_citation_graph: None
):
    doc_a_id, doc_b_id = f"doc-a-{owner_id}", f"doc-b-{owner_id}"
    _, chunk_ids_a = _ingest(neo4j_driver, owner_id, DOC_A_TEXT, doc_a_id, "Nghị định 99/2024")
    _, chunk_ids_b = _ingest(neo4j_driver, owner_id, DOC_B_TEXT, doc_b_id, "Nghị định 88/2019")

    # Giả lập dense search trúng chunk chứa Điều 1 Khoản 1 của A (nêu câu viện dẫn).
    seed_chunk_ids = [chunk_ids_a[0]]

    result = graph_augmented_search(
        seed_chunk_ids=seed_chunk_ids,
        document_ids=[doc_a_id, doc_b_id],
        owner_id=owner_id,
    )

    context_doc_ids = {c.document_id for c in result.context_chunks}
    assert doc_a_id in context_doc_ids, "Provision neo (A) phải có trong context"
    assert doc_b_id in context_doc_ids, (
        "Provision được viện dẫn (B) phải có trong context khi B đã gắn hội thoại"
    )
    assert result.suggested_documents == [], "B đã gắn hội thoại — không cần gợi ý"

    # Audit trail phải ghi lại bước traverse A -> B.
    assert any(
        step["relation"] == "VIEN_DAN" and step["in_context"] for step in result.citation_graph_path
    )


def test_only_a_attached_puts_b_in_suggestions_not_context(
    neo4j_driver: Driver, owner_id: str, patch_neo4j_driver, cleanup_citation_graph: None
):
    doc_a_id, doc_b_id = f"doc-a-{owner_id}", f"doc-b-{owner_id}"
    _, chunk_ids_a = _ingest(neo4j_driver, owner_id, DOC_A_TEXT, doc_a_id, "Nghị định 99/2024")
    _, _ = _ingest(neo4j_driver, owner_id, DOC_B_TEXT, doc_b_id, "Nghị định 88/2019")

    result = graph_augmented_search(
        seed_chunk_ids=[chunk_ids_a[0]],
        document_ids=[doc_a_id],  # CHỈ A gắn vào hội thoại
        owner_id=owner_id,
    )

    context_doc_ids = {c.document_id for c in result.context_chunks}
    assert doc_a_id in context_doc_ids
    assert doc_b_id not in context_doc_ids, "B chưa gắn hội thoại — KHÔNG được vào context"

    suggestions = {s["document_code"]: s for s in result.suggested_documents}
    assert "88/2019/NĐ-CP" in suggestions
    assert suggestions["88/2019/NĐ-CP"]["in_library"] is True
    assert suggestions["88/2019/NĐ-CP"]["document_id"] == doc_b_id


def test_citation_to_document_not_in_library_is_suggested_without_library_flag(
    neo4j_driver: Driver, owner_id: str, patch_neo4j_driver, cleanup_citation_graph: None
):
    """A viện dẫn B, nhưng B CHƯA từng được ingest -> placeholder Provision -> gợi ý
    in_library=False (đúng khác biệt với case B đã có nhưng chưa gắn hội thoại)."""
    doc_a_id = f"doc-a-{owner_id}"
    _, chunk_ids_a = _ingest(neo4j_driver, owner_id, DOC_A_TEXT, doc_a_id, "Nghị định 99/2024")

    result = graph_augmented_search(
        seed_chunk_ids=[chunk_ids_a[0]],
        document_ids=[doc_a_id],
        owner_id=owner_id,
    )

    suggestions = {s["document_code"]: s for s in result.suggested_documents}
    assert "88/2019/NĐ-CP" in suggestions
    assert suggestions["88/2019/NĐ-CP"]["in_library"] is False
    assert suggestions["88/2019/NĐ-CP"]["document_id"] is None
    assert all(c.document_id != "" for c in result.context_chunks), (
        "placeholder không được lọt vào context"
    )


def test_owner_isolation_traversal_never_leaks_other_owner_nodes(
    neo4j_driver: Driver, patch_neo4j_driver
):
    """2 owner ingest 2 văn bản CÙNG nội dung (cùng document_code) — namespace
    legal_address theo owner_id nên đây là 2 cặp node hoàn toàn tách biệt. Traverse
    của owner1 không bao giờ được với sang Provision/LegalDocument của owner2."""
    owner1, owner2 = f"test_{uuid.uuid4().hex[:12]}", f"test_{uuid.uuid4().hex[:12]}"
    try:
        doc_a1, doc_b1 = f"doc-a-{owner1}", f"doc-b-{owner1}"
        doc_a2, doc_b2 = f"doc-a-{owner2}", f"doc-b-{owner2}"
        _, chunk_ids_a1 = _ingest(
            neo4j_driver, owner1, DOC_A_TEXT, doc_a1, "Nghị định 99/2024 (owner1)"
        )
        _ingest(neo4j_driver, owner1, DOC_B_TEXT, doc_b1, "Nghị định 88/2019 (owner1)")
        _ingest(neo4j_driver, owner2, DOC_A_TEXT, doc_a2, "Nghị định 99/2024 (owner2)")
        _ingest(neo4j_driver, owner2, DOC_B_TEXT, doc_b2, "Nghị định 88/2019 (owner2)")

        result = graph_augmented_search(
            seed_chunk_ids=[chunk_ids_a1[0]],
            document_ids=[doc_a1, doc_b1, doc_a2, doc_b2],  # owner2 doc lẫn vào scope
            owner_id=owner1,
        )

        context_doc_ids = {c.document_id for c in result.context_chunks}
        assert doc_a1 in context_doc_ids
        assert doc_b1 in context_doc_ids
        assert doc_a2 not in context_doc_ids
        assert doc_b2 not in context_doc_ids
    finally:
        with neo4j_driver.session() as session:
            for o in (owner1, owner2):
                session.run("MATCH (p:Provision {owner_id: $o}) DETACH DELETE p", o=o)
                session.run("MATCH (d:LegalDocument {owner_id: $o}) DETACH DELETE d", o=o)
                session.run(
                    "MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH $prefix DETACH DELETE c",
                    prefix=f"{o}-",
                )
