"""
Integration test — Provision layer (citation graph Phase 1 + Phase 2) trên Neo4j THẬT.

QUAN TRỌNG: KHÔNG dùng app.rag.graph_client.get_neo4j_driver() — driver đó đọc
settings.NEO4J_URI, và backend/.env hiện trỏ Neo4j Aura CLOUD (production graph
dùng cho retrieval thật). Test này tự tạo driver riêng trỏ Neo4j LOCAL
(docker-compose: `docker compose up -d neo4j`, xem backend/docker-compose.yml) để
không bao giờ lỡ ghi dữ liệu test vào graph production. Override qua env
NEO4J_TEST_URI / NEO4J_TEST_USER / NEO4J_TEST_PASSWORD nếu cần (vd CI sau này thêm
service Neo4j với credentials khác).

Tự SKIP (không FAIL) nếu không kết nối được Neo4j local — không bắt buộc mọi lần
chạy test suite phải có Neo4j (`pytest app/tests/unit/` không đụng file này; CI
job test-integration hiện chưa provision service Neo4j nên sẽ skip, không đỏ CI).

Logic + sample text chuyển thẳng từ script chạy tay đã verify runtime (10 Provision,
14 HAS_CHUNK, 4 VIEN_DAN, idempotent qua 2 lần MERGE) — xem lịch sử trò chuyện lúc
verify Provision layer Phase 1 trên Neo4j local.
"""

import os
import uuid
from collections.abc import Iterator

import pytest
from neo4j import Driver, GraphDatabase

from app.ingestion.chunker import DocumentChunker
from app.ingestion.graph_indexer import (
    ProvisionRecord,
    index_external_placeholders_to_graph,
    index_provisions_to_graph,
)
from app.ingestion.structural_parser import (
    ParsedCitation,
    ParsedProvision,
    extract_citations,
    extract_document_code,
    extract_external_citations,
    parse_provisions,
)
from app.rag.graph_client import ensure_graph_schema

pytestmark = pytest.mark.neo4j

_TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
_TEST_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "neo4j_password")

SAMPLE_TEXT = """Nghị định số 99/2024/NĐ-CP quy định về bảo vệ dữ liệu cá nhân

Điều 1. Phạm vi điều chỉnh
1. Nghị định này quy định về bảo vệ dữ liệu cá nhân trong hoạt động xử lý dữ liệu.
2. Trường hợp vi phạm quy định tại khoản 1 Điều 5 của Nghị định này sẽ bị xử lý theo Điều 10.

Điều 5. Nguyên tắc xử lý dữ liệu
1. Dữ liệu cá nhân phải được xử lý theo quy định tại điểm a khoản 1 Điều 1.
2. Việc thu thập dữ liệu phải tuân thủ các nguyên tắc sau:
   a) Minh bạch và hợp pháp;
   b) Giới hạn theo mục đích quy định tại Điều 10.

Điều 10. Xử lý vi phạm
1. Tổ chức vi phạm Điều 5 sẽ bị xử phạt hành chính.
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
    # Namespace riêng mỗi lần chạy test (prefix test_) để không đụng dữ liệu thật
    # và không đụng lẫn nhau giữa các lần chạy test song song.
    return f"test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def cleanup_provision_graph(neo4j_driver: Driver, owner_id: str) -> Iterator[None]:
    yield
    with neo4j_driver.session() as session:
        session.run("MATCH (p:Provision {owner_id: $o}) DETACH DELETE p", o=owner_id)
        session.run(
            "MATCH (c:Chunk) WHERE c.chunk_id STARTS WITH $prefix DETACH DELETE c",
            prefix=f"{owner_id}-chunk-",
        )


def _index_sample(
    driver: Driver, owner_id: str
) -> tuple[list[ParsedProvision], list[tuple], list[ParsedCitation]]:
    """Chạy đúng luồng bước 10b của ingest_document (ingestion.py:213-292) trên
    SAMPLE_TEXT, ghi vào Neo4j *driver* dưới namespace *owner_id*."""
    provisions = parse_provisions(SAMPLE_TEXT)
    document_code = extract_document_code(SAMPLE_TEXT) or f"internal:{owner_id}"
    citations = extract_citations(SAMPLE_TEXT, provisions)

    chunker = DocumentChunker(chunk_size=200, chunk_overlap=40)
    chunks = chunker.chunk(SAMPLE_TEXT)

    chunk_links: list[tuple[tuple[int, int | None, str | None], str]] = []
    for p in provisions:
        for chunk in chunks:
            c_start = chunk.char_start
            c_end = c_start + len(chunk.content)
            if c_start < p.char_end and c_end > p.char_start:
                chunk_links.append(
                    ((p.key.dieu, p.key.khoan, p.key.diem), f"{owner_id}-chunk-{chunk.chunk_index}")
                )

    with driver.session() as session:
        session.run(
            "UNWIND $ids AS cid MERGE (c:Chunk {chunk_id: cid})",
            ids=[f"{owner_id}-chunk-{c.chunk_index}" for c in chunks],
        )

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
        driver=driver,
        owner_id=owner_id,
        document_code=document_code,
        provisions=provision_records,
        chunk_links=chunk_links,
        citations=citation_pairs,
    )
    return provisions, chunk_links, citations


def _counts(driver: Driver, owner_id: str) -> tuple[int, int, int]:
    with driver.session() as session:
        n_provisions = session.run(
            "MATCH (p:Provision {owner_id: $o}) RETURN count(p) AS n", o=owner_id
        ).single()["n"]
        n_has_chunk = session.run(
            "MATCH (:Provision {owner_id: $o})-[r:HAS_CHUNK]->(:Chunk) RETURN count(r) AS n",
            o=owner_id,
        ).single()["n"]
        n_vien_dan = session.run(
            "MATCH (:Provision {owner_id: $o})-[r:VIEN_DAN]->(:Provision) RETURN count(r) AS n",
            o=owner_id,
        ).single()["n"]
    return n_provisions, n_has_chunk, n_vien_dan


def test_index_provisions_to_graph_creates_expected_nodes_and_edges(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    provisions, chunk_links, citations = _index_sample(neo4j_driver, owner_id)

    n_provisions, n_has_chunk, n_vien_dan = _counts(neo4j_driver, owner_id)
    assert n_provisions == len(provisions) == 10
    assert n_has_chunk == len(chunk_links)
    assert n_vien_dan == len(citations) == 4


def test_index_provisions_to_graph_is_idempotent(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    """MERGE phải hội tụ về cùng 1 tập node/edge dù chạy lại nhiều lần (retry Celery,
    reindex) — không được nhân đôi. Đây là ca giá trị nhất đã verify tay trước đó."""
    _index_sample(neo4j_driver, owner_id)
    first = _counts(neo4j_driver, owner_id)
    assert first[0] > 0, "setup không tạo ra Provision nào — test vô nghĩa"

    _index_sample(neo4j_driver, owner_id)
    second = _counts(neo4j_driver, owner_id)

    assert first == second


def test_legal_address_format_on_real_nodes(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    _index_sample(neo4j_driver, owner_id)

    with neo4j_driver.session() as session:
        rows = list(
            session.run("MATCH (p:Provision {owner_id: $o}) RETURN p.legal_address AS addr", o=owner_id)
        )
    addresses = {r["addr"] for r in rows}

    assert all(a.startswith(f"owner_{owner_id}:99/2024/NĐ-CP:") for a in addresses)
    assert f"owner_{owner_id}:99/2024/NĐ-CP:DIEU_1:KHOAN_1" in addresses
    assert f"owner_{owner_id}:99/2024/NĐ-CP:DIEU_5:KHOAN_2:DIEM_a" in addresses
    assert f"owner_{owner_id}:99/2024/NĐ-CP:DIEU_5:KHOAN_2:DIEM_b" in addresses


def test_provision_address_unique_constraint_exists(neo4j_driver: Driver):
    with neo4j_driver.session() as session:
        constraints = list(session.run("SHOW CONSTRAINTS YIELD name RETURN name"))
    names = {row["name"] for row in constraints}
    assert "provision_address_unique" in names


# ── Phase 2 — placeholder cho viện dẫn NGOẠI ─────────────────────────────────

EXTERNAL_SAMPLE_TEXT = """Nghị định số 99/2024/NĐ-CP quy định về bảo vệ dữ liệu cá nhân

Điều 1. Phạm vi điều chỉnh
1. Việc xử lý vi phạm được thực hiện theo quy định tại Điều 5 Nghị định số 88/2019/NĐ-CP.
"""


def _index_external_sample(driver: Driver, owner_id: str) -> None:
    """Chạy đúng luồng bước 10b (C1 + index_provisions_to_graph) rồi bước 10c
    (C2 + index_external_placeholders_to_graph) của ingest_document trên
    EXTERNAL_SAMPLE_TEXT — nguồn viện dẫn (Điều 1 Khoản 1) phải tồn tại THẬT trước
    khi tạo cạnh VIEN_DAN trỏ ra placeholder."""
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    document_code = extract_document_code(EXTERNAL_SAMPLE_TEXT)
    assert document_code == "99/2024/NĐ-CP"

    provision_records = [
        ProvisionRecord(dieu=p.key.dieu, khoan=p.key.khoan, diem=p.key.diem, content=p.content)
        for p in provisions
    ]
    index_provisions_to_graph(
        driver=driver,
        owner_id=owner_id,
        document_code=document_code,
        provisions=provision_records,
        chunk_links=[],
        citations=[],
    )

    external_citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, document_code)
    resolvable = [
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
    index_external_placeholders_to_graph(
        driver=driver,
        owner_id=owner_id,
        own_document_code=document_code,
        citations=resolvable,
    )


def test_external_placeholder_created_with_is_placeholder_true(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    _index_external_sample(neo4j_driver, owner_id)

    target_addr = f"owner_{owner_id}:88/2019/NĐ-CP:DIEU_5"
    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (p:Provision {legal_address: $addr}) RETURN p.is_placeholder AS ph, "
            "p.content AS content, p.owner_id AS owner_id, p.document_code AS document_code, "
            "p.dieu AS dieu",
            addr=target_addr,
        ).single()

    assert record is not None, "placeholder Provision không được tạo"
    assert record["ph"] is True
    assert record["content"] is None
    assert record["owner_id"] == owner_id
    assert record["document_code"] == "88/2019/NĐ-CP"
    assert record["dieu"] == 5


def test_external_placeholder_has_vien_dan_edge_from_citing_provision(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    _index_external_sample(neo4j_driver, owner_id)

    source_addr = f"owner_{owner_id}:99/2024/NĐ-CP:DIEU_1:KHOAN_1"
    target_addr = f"owner_{owner_id}:88/2019/NĐ-CP:DIEU_5"
    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (a:Provision {legal_address: $src})-[:VIEN_DAN]->(b:Provision {legal_address: $dst}) "
            "RETURN count(*) AS n",
            src=source_addr,
            dst=target_addr,
        ).single()
    assert record["n"] == 1


def test_external_placeholder_is_idempotent_across_two_runs(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    _index_external_sample(neo4j_driver, owner_id)
    _index_external_sample(neo4j_driver, owner_id)

    with neo4j_driver.session() as session:
        n_placeholders = session.run(
            "MATCH (p:Provision {owner_id: $o, is_placeholder: true}) RETURN count(p) AS n",
            o=owner_id,
        ).single()["n"]
        n_edges = session.run(
            "MATCH (:Provision {owner_id: $o})-[r:VIEN_DAN]->(:Provision {is_placeholder: true}) "
            "RETURN count(r) AS n",
            o=owner_id,
        ).single()["n"]

    assert n_placeholders == 1, "MERGE trùng địa chỉ phải gộp, không nhân đôi placeholder"
    assert n_edges == 1


def test_external_placeholder_does_not_overwrite_real_provision_ingested_later(
    neo4j_driver: Driver, owner_id: str, cleanup_provision_graph: None
):
    """Mô phỏng thứ tự: (1) văn bản A viện dẫn ngoại tới văn bản B (B chưa ingest)
    -> placeholder được tạo cho B. (2) B sau đó được ingest THẬT (cùng owner,
    document_code trùng khớp) -> node hội tụ, content/is_placeholder được cập nhật
    thành thật. (3) Giả lập có thêm 1 viện dẫn ngoại KHÁC cũng trỏ tới B — bước
    index_external_placeholders_to_graph này KHÔNG được phép đè content thật của B
    trở lại thành placeholder (ON CREATE SET chỉ áp dụng khi node CHƯA tồn tại)."""
    _index_external_sample(neo4j_driver, owner_id)

    target_addr = f"owner_{owner_id}:88/2019/NĐ-CP:DIEU_5"

    # (2) B được ingest thật — index_provisions_to_graph SET is_placeholder=false
    # + content thật, MERGE hội tụ vào đúng node placeholder đã tạo ở bước (1).
    index_provisions_to_graph(
        driver=neo4j_driver,
        owner_id=owner_id,
        document_code="88/2019/NĐ-CP",
        provisions=[ProvisionRecord(dieu=5, khoan=None, diem=None, content="Nội dung Điều 5 thật")],
        chunk_links=[],
        citations=[],
    )

    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (p:Provision {legal_address: $addr}) RETURN p.is_placeholder AS ph, "
            "p.content AS content",
            addr=target_addr,
        ).single()
    assert record["ph"] is False
    assert record["content"] == "Nội dung Điều 5 thật"

    # (3) Chạy lại index_external_placeholders_to_graph cho CÙNG đích — node đã
    # tồn tại (thật) nên ON CREATE SET không chạy, nội dung thật phải giữ nguyên.
    index_external_placeholders_to_graph(
        driver=neo4j_driver,
        owner_id=owner_id,
        own_document_code="99/2024/NĐ-CP",
        citations=[((1, 1, None), "88/2019/NĐ-CP", 5, None, None)],
    )

    with neo4j_driver.session() as session:
        record = session.run(
            "MATCH (p:Provision {legal_address: $addr}) RETURN p.is_placeholder AS ph, "
            "p.content AS content",
            addr=target_addr,
        ).single()
    assert record["ph"] is False, "node thật KHÔNG được đè lại thành placeholder"
    assert record["content"] == "Nội dung Điều 5 thật"
