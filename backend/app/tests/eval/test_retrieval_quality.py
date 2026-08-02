"""
Eval harness — đo chất lượng retrieval, trọng tâm: chế độ "Nâng cao" (citation graph,
search_mode="advanced") tốt hơn Hybrid (search_mode="hybrid") bao nhiêu ở câu hỏi cần
lần theo viện dẫn (Nhóm A), và KHÔNG làm tệ đi ở câu hỏi trực tiếp (Nhóm B).

KHÔNG mock retrieval — ingest golden_set.json (app/tests/eval/golden_set.json) qua đúng
pipeline production (DocumentChunker → OpenAIEmbedder → Qdrant Cloud thật, structural_parser
+ graph_indexer → Neo4j thật), rồi gọi thẳng retriever_node()/generator_node() (không qua
HTTP) cho từng câu hỏi x2 mode.

Yêu cầu hạ tầng để chạy:
  - Neo4j LOCAL đang chạy (docker compose up -d neo4j ở backend/), KHÔNG BAO GIỜ chạm Neo4j
    Aura production mà settings.NEO4J_URI trỏ tới — cùng cách ly như
    app/tests/integration/test_citation_retrieval.py (monkeypatch get_neo4j_driver).
  - OPENAI_API_KEY hợp lệ trong backend/.env (embedding + generation — TỐN TIỀN thật, dù rẻ:
    ~11 câu x 2 mode x (1 embed query + 1 generation gpt-4o-mini) + embed ~5 văn bản ngắn).
  - QDRANT_URL/QDRANT_API_KEY hợp lệ — ghi thật vào collection Qdrant Cloud đang dùng, có
    owner_id riêng (prefix "eval_") để cô lập khỏi dữ liệu user thật, XÓA SẠCH ở cuối test
    (finally) dù pass hay fail.

Cách chạy (từ backend/):
  uv run pytest -m eval -s app/tests/eval/test_retrieval_quality.py

  -s bắt buộc để thấy bảng kết quả in ra (pytest mặc định capture stdout).
  EVAL_SKIP_GENERATION=1 uv run pytest -m eval -s ...   # bỏ bước generator_node (LLM),
                                                          # chỉ đo retrieval hit + rank —
                                                          # nhanh/rẻ hơn khi lặp lại nhiều lần.

KHÔNG chạy trong CI mặc định: nằm ngoài app/tests/unit và app/tests/integration (2 đường dẫn
CI thật sự chạy, xem .github/workflows/ci.yml) NÊN không bị `uv run pytest app/tests/unit/ ...`
của CI nhặt vào — chỉ chạy tay bằng lệnh trên. Marker `eval` (đăng ký ở pyproject.toml) cũng tự
skip nếu Neo4j local / OPENAI_API_KEY / QDRANT_URL không sẵn sàng, để một `uv run pytest` toàn
bộ vô tình gom app/tests/eval/ vào không bị lỗi khó hiểu.

Phương pháp đo answer-correctness: SO KHỚP TỪ KHÓA đơn giản (không LLM-judge) — mỗi câu hỏi
trong golden_set.json có `expected_keywords`; câu trả lời cuối coi là đúng nếu chứa (không phân
biệt hoa/thường) ÍT NHẤT MỘT trong các từ khóa đó. Không dùng LLM chấm vì thêm 1 lớp LLM không
xác định (chính LLM chấm cũng có thể sai) trong khi các câu hỏi ở đây có đáp án đủ cụ thể
(số tiền, thời hạn, tên cơ quan) để so khớp từ khóa đáng tin cậy.

Đây là công cụ ĐO — không sửa logic retrieval/graph. Nếu kết quả cho thấy chất lượng kém ở đâu,
ghi lại trong báo cáo, không tự vá ở đây.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import pytest
from neo4j import Driver, GraphDatabase
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.agents.generator import generator_node
from app.agents.retriever import retriever_node
from app.agents.state import AgentState
from app.core.config import settings
from app.ingestion.chunker import DocumentChunker
from app.ingestion.embedder import get_embedder
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
from app.rag.graph_client import ensure_graph_schema
from app.rag.reranker import get_reranker
from app.rag.retriever import get_qdrant_client

pytestmark = pytest.mark.eval

_NEO4J_TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7687")
_NEO4J_TEST_USER = os.environ.get("NEO4J_TEST_USER", "neo4j")
_NEO4J_TEST_PASSWORD = os.environ.get("NEO4J_TEST_PASSWORD", "neo4j_password")

# Namespace riêng cho chunk_id sinh ra trong eval — KHÔNG dùng chung với
# _CHUNK_ID_NAMESPACE của app/workers/tasks/ingestion.py để không thể trùng UUID
# với chunk thật (dù xác suất coi như 0, tách namespace vẫn rõ ràng hơn).
_EVAL_CHUNK_NAMESPACE = uuid.UUID("7e5a1e00-eba1-4000-8eba-1eba1eba1eba")

_MODES: tuple[Literal["hybrid", "advanced"], ...] = ("hybrid", "advanced")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def neo4j_driver() -> Iterator[Driver]:
    driver = GraphDatabase.driver(_NEO4J_TEST_URI, auth=(_NEO4J_TEST_USER, _NEO4J_TEST_PASSWORD))
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        driver.close()
        pytest.skip(f"Neo4j local không sẵn sàng tại {_NEO4J_TEST_URI}: {exc}")
    ensure_graph_schema(driver)
    yield driver
    driver.close()


# ── Golden set loading ───────────────────────────────────────────────────────


def _load_golden_set() -> dict:
    path = Path(__file__).parent / "golden_set.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ── Ingestion helpers (mirror app/workers/tasks/ingestion.py, không qua Celery/S3) ──


def _ensure_qdrant_ready(qdrant, embedder) -> None:
    existing = [c.name for c in qdrant.get_collections().collections]
    if settings.QDRANT_COLLECTION_NAME not in existing:
        qdrant.create_collection(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            vectors_config=VectorParams(size=embedder.dimension, distance=Distance.COSINE),
        )
    for field in ("owner_id", "document_id"):
        try:
            qdrant.create_payload_index(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:  # noqa: BLE001 — idempotent, index đã tồn tại là bình thường
            pass


def _ingest_document(
    qdrant,
    driver: Driver,
    embedder,
    owner_id: str,
    document_id: str,
    document_name: str,
    text: str,
) -> None:
    """Chunk → embed → Qdrant, rồi Chunk-graph + Provision-graph vào Neo4j — cùng thứ tự
    bước 4-10b của ingest_document() thật, tối giản (bỏ S3/Postgres/Celery, không cần
    cho eval) và bỏ implicit-citation LLM fallback (golden set chỉ dùng viện dẫn tường
    minh, không cần fallback đó)."""
    chunker = DocumentChunker()  # dùng đúng CHUNK_SIZE/CHUNK_OVERLAP production
    chunks = chunker.chunk(
        text, metadata={"document_id": document_id, "document_name": document_name}
    )
    embeddings = embedder.embed([c.content for c in chunks])

    chunk_ids = [
        str(uuid.uuid5(_EVAL_CHUNK_NAMESPACE, f"{owner_id}:{document_id}:{c.chunk_index}"))
        for c in chunks
    ]

    points = [
        PointStruct(
            id=cid,
            vector=emb,
            payload={
                "document_id": document_id,
                "document_name": document_name,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "owner_id": owner_id,
            },
        )
        for cid, c, emb in zip(chunk_ids, chunks, embeddings, strict=True)
    ]
    qdrant.upsert(collection_name=settings.QDRANT_COLLECTION_NAME, points=points, wait=True)

    chunk_records = [
        ChunkRecord(chunk_id=cid, content=c.content, chunk_index=c.chunk_index)
        for cid, c in zip(chunk_ids, chunks, strict=True)
    ]
    index_chunks_to_graph(driver, document_id, document_name, chunk_records, owner_id=owner_id)

    provisions = parse_provisions(text)
    if not provisions:
        return  # golden set toàn văn bản luật — không nên xảy ra, nhưng graceful nếu có

    document_code = extract_document_code(text)
    assert document_code is not None, f"Không tách được document_code cho {document_name}"

    citations = extract_citations(text, provisions)
    external_citations = extract_external_citations(text, provisions, document_code)

    chunk_links: list[tuple[tuple[int, int | None, str | None], str]] = []
    for p in provisions:
        for cid, c in zip(chunk_ids, chunks, strict=True):
            if c.char_start is None:
                continue
            c_start = c.char_start
            c_end = c_start + len(c.content)
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


def _cleanup(qdrant, driver: Driver, owner_id: str) -> None:
    try:
        qdrant.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="owner_id", match=MatchValue(value=owner_id))]
            ),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[eval cleanup] Qdrant delete thất bại (owner_id={owner_id}): {exc}")

    with driver.session() as session:
        session.run("MATCH (c:Chunk {owner_id: $o}) DETACH DELETE c", o=owner_id)
        session.run("MATCH (p:Provision {owner_id: $o}) DETACH DELETE p", o=owner_id)
        session.run("MATCH (d:LegalDocument {owner_id: $o}) DETACH DELETE d", o=owner_id)


# ── Matching + reporting ─────────────────────────────────────────────────────


def _build_initial_state(
    query: str,
    document_ids: list[str],
    owner_id: str,
    search_mode: Literal["hybrid", "advanced"],
) -> AgentState:
    return AgentState(
        query=query,
        intent="rag",
        rewritten_query=None,
        dense_results=[],
        graph_results=[],
        merged_results=[],
        reranked_results=[],
        citations=[],
        final_answer=None,
        confidence_score=0.0,
        retry_count=0,
        search_tool=False,
        document_ids=document_ids,
        owner_id=owner_id,
        search_mode=search_mode,
        citation_graph_path=[],
        citation_graph_nodes=[],
        suggested_documents=[],
        top_k=None,
        similarity_threshold=None,
        system_prompt=None,
        model=None,
        api_key=None,
        base_url=None,
        image_data_urls=None,
    )


def _chunk_matches(chunk, expected_document_id: str, expected_keywords: list[str]) -> bool:
    if chunk.document_id != expected_document_id:
        return False
    content_lower = chunk.content.lower()
    return any(kw.lower() in content_lower for kw in expected_keywords)


def _print_report(rows: list[dict]) -> None:
    print("\n" + "=" * 88)
    print("RETRIEVAL QUALITY EVAL — hybrid vs advanced (citation graph)")
    print("=" * 88)

    header = (
        f"{'ID':<5}{'Group':<7}{'Mode':<10}{'Hit(pool)':<11}{'Rank@rerank':<13}{'AnswerOK':<10}"
    )
    print(header)
    print("-" * len(header))
    for r in rows:
        rank_str = str(r["rank"]) if r["rank"] else "-"
        ans_str = "n/a" if r["answer_correct"] is None else ("YES" if r["answer_correct"] else "no")
        print(
            f"{r['id']:<5}{r['group']:<7}{r['mode']:<10}"
            f"{'YES' if r['hit'] else 'no':<11}{rank_str:<13}{ans_str:<10}"
        )

    print()
    print("SUMMARY BY GROUP x MODE")
    print("-" * 88)
    for group, label in (
        ("A", "A - citation-hop (graph phải thắng)"),
        ("B", "B - truc tiep (graph khong duoc lam te hon)"),
    ):
        for mode in _MODES:
            subset = [r for r in rows if r["group"] == group and r["mode"] == mode]
            if not subset:
                continue
            n = len(subset)
            hit_rate = 100 * sum(r["hit"] for r in subset) / n
            ranks = [r["rank"] for r in subset if r["rank"]]
            avg_rank = f"{sum(ranks) / len(ranks):.1f}" if ranks else "-"
            ans_rows = [r for r in subset if r["answer_correct"] is not None]
            ans_rate = (
                f"{100 * sum(r['answer_correct'] for r in ans_rows) / len(ans_rows):.0f}%"
                if ans_rows
                else "n/a"
            )
            print(
                f"  Nhom {label:<45} mode={mode:<9} "
                f"hit={hit_rate:5.0f}%  avg_rank={avg_rank:<5}  answer_correct={ans_rate}"
            )
    print("=" * 88 + "\n")


# ── Main eval ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_quality_baseline(neo4j_driver: Driver, monkeypatch):
    if not settings.OPENAI_API_KEY:
        pytest.skip("OPENAI_API_KEY chưa cấu hình — eval cần gọi OpenAI embedding/LLM thật")
    if not settings.QDRANT_URL:
        pytest.skip("QDRANT_URL chưa cấu hình")

    # app/rag/retriever.py._graph_search và app/rag/citation_retriever.py đều lazy-import
    # get_neo4j_driver từ app.rag.graph_client bên trong hàm — patch thẳng module attribute
    # để cả 2 trỏ về Neo4j LOCAL thay vì Aura production (settings.NEO4J_URI).
    monkeypatch.setattr("app.rag.graph_client.get_neo4j_driver", lambda: neo4j_driver)

    owner_id = f"eval_{uuid.uuid4().hex[:12]}"
    dataset = _load_golden_set()
    qdrant = get_qdrant_client()
    embedder = get_embedder()
    reranker = get_reranker()
    skip_generation = os.environ.get("EVAL_SKIP_GENERATION") == "1"

    doc_id_map: dict[str, str] = {}

    try:
        _ensure_qdrant_ready(qdrant, embedder)

        for doc in dataset["documents"]:
            real_id = str(uuid.uuid4())
            doc_id_map[doc["id"]] = real_id
            _ingest_document(
                qdrant, neo4j_driver, embedder, owner_id, real_id, doc["name"], doc["text"]
            )

        rows: list[dict] = []
        for q in dataset["questions"]:
            expected_real_id = doc_id_map[q["expected_document_id"]]
            attached_ids = [doc_id_map[d] for d in q["attached_document_ids"]]
            expected_keywords = q["expected_keywords"]

            for mode in _MODES:
                state = _build_initial_state(q["query"], attached_ids, owner_id, mode)
                result_state = await retriever_node(state)
                merged = result_state["merged_results"]

                hit = any(_chunk_matches(c, expected_real_id, expected_keywords) for c in merged)
                reranked = reranker.rerank(q["query"], merged, top_k=None)
                rank = next(
                    (
                        i + 1
                        for i, c in enumerate(reranked)
                        if _chunk_matches(c, expected_real_id, expected_keywords)
                    ),
                    None,
                )

                answer_correct: bool | None = None
                if not skip_generation:
                    gen_state: AgentState = {**result_state, "reranked_results": reranked}
                    gen_result = await generator_node(gen_state)
                    final_answer = gen_result.get("final_answer") or ""
                    answer_correct = any(
                        kw.lower() in final_answer.lower() for kw in expected_keywords
                    )

                rows.append(
                    {
                        "id": q["id"],
                        "group": q["group"],
                        "mode": mode,
                        "hit": hit,
                        "rank": rank,
                        "answer_correct": answer_correct,
                    }
                )

        _print_report(rows)
        assert len(rows) == len(dataset["questions"]) * len(_MODES)
    finally:
        _cleanup(qdrant, neo4j_driver, owner_id)
