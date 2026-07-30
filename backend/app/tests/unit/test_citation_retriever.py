"""Unit test cho phần logic thuần (không cần Neo4j) của rag/citation_retriever.py:
_owner_clause, _in_scope, và bộ phân loại context-vs-suggestion _classify.

Test Neo4j-dependent (Cypher traversal thật) nằm ở
tests/integration/test_citation_retrieval.py (@pytest.mark.neo4j)."""

from app.rag.citation_retriever import _classify, _in_scope, _owner_clause

# ── _owner_clause ─────────────────────────────────────────────────────────────


def test_owner_clause_with_owner_id():
    assert _owner_clause("p", "owner-1") == "AND p.owner_id = $owner_id"


def test_owner_clause_admin_none_is_unfiltered():
    assert _owner_clause("p", None) == ""


# ── _in_scope ──────────────────────────────────────────────────────────────────


def test_in_scope_document_ids_none_means_unrestricted():
    assert _in_scope("doc-1", None) is True


def test_in_scope_unresolved_document_id_is_always_out_of_scope():
    # document_id=None nghĩa là không resolve được document -> không có gì để gộp,
    # kể cả khi document_ids=None (không giới hạn).
    assert _in_scope(None, None) is False
    assert _in_scope(None, ["doc-1"]) is False


def test_in_scope_document_id_in_list():
    assert _in_scope("doc-1", ["doc-1", "doc-2"]) is True


def test_in_scope_document_id_not_in_list():
    assert _in_scope("doc-3", ["doc-1", "doc-2"]) is False


# ── _classify: anchor Provision ───────────────────────────────────────────────


def test_classify_anchor_always_goes_to_context():
    anchors = {
        "owner_x:LAW1:DIEU_5": {
            "legal_address": "owner_x:LAW1:DIEU_5",
            "document_code": "LAW1",
            "content": "Nội dung Điều 5",
            "chunk_id": "chunk-1",
            "document_id": "doc-A",
            "document_name": "Luật A",
        }
    }
    result = _classify(anchors, {}, [], document_ids=["doc-A"])

    assert len(result.context_chunks) == 1
    assert result.context_chunks[0].chunk_id == "chunk-1"
    assert result.context_chunks[0].document_id == "doc-A"
    assert result.suggested_documents == []
    assert result.citation_graph_path == []


def test_classify_anchor_in_context_even_when_document_ids_excludes_it():
    # Anchor đã owner/document-scoped từ _dense_search TRƯỚC khi tới traversal —
    # _classify không re-check document_ids cho anchor.
    anchors = {
        "owner_x:LAW1:DIEU_5": {
            "legal_address": "owner_x:LAW1:DIEU_5",
            "document_code": "LAW1",
            "content": "Nội dung Điều 5",
            "chunk_id": "chunk-1",
            "document_id": "doc-A",
            "document_name": "Luật A",
        }
    }
    result = _classify(anchors, {}, [], document_ids=["doc-other"])
    assert len(result.context_chunks) == 1


# ── _classify: related Provision (VIEN_DAN traversal) ─────────────────────────


def _related_row(**overrides) -> dict:
    row = {
        "anchor_addr": "owner_x:LAW1:DIEU_5",
        "legal_address": "owner_x:LAW2:DIEU_10",
        "document_code": "LAW2",
        "content": "Nội dung Điều 10 của Luật 2",
        "is_placeholder": False,
        "hops": 1,
        "chunk_id": "chunk-2",
        "document_id": "doc-B",
        "document_name": "Luật B",
    }
    row.update(overrides)
    return row


def test_classify_related_real_in_scope_goes_to_context():
    related = {"owner_x:LAW2:DIEU_10": _related_row()}
    result = _classify({}, related, [], document_ids=["doc-A", "doc-B"])

    assert len(result.context_chunks) == 1
    assert result.context_chunks[0].chunk_id == "chunk-2"
    assert result.suggested_documents == []
    assert result.citation_graph_path == [
        {
            "from_address": "owner_x:LAW1:DIEU_5",
            "to_address": "owner_x:LAW2:DIEU_10",
            "relation": "VIEN_DAN",
            "hops": 1,
            "in_context": True,
        }
    ]


def test_classify_related_real_out_of_scope_becomes_suggestion():
    # doc-B tồn tại trong thư viện owner nhưng KHÔNG nằm trong document_ids đã gắn
    # vào hội thoại (chỉ doc-A) -> gợi ý, KHÔNG gộp context.
    related = {"owner_x:LAW2:DIEU_10": _related_row()}
    result = _classify({}, related, [], document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.suggested_documents == [
        {
            "document_code": "LAW2",
            "document_id": "doc-B",
            "name": "Luật B",
            "in_library": True,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]
    assert result.citation_graph_path[0]["in_context"] is False


def test_classify_related_real_document_ids_none_is_in_scope():
    related = {"owner_x:LAW2:DIEU_10": _related_row()}
    result = _classify({}, related, [], document_ids=None)

    assert len(result.context_chunks) == 1
    assert result.suggested_documents == []


def test_classify_related_placeholder_becomes_suggestion_not_in_library():
    related = {
        "owner_x:LAW3:DIEU_1": _related_row(
            legal_address="owner_x:LAW3:DIEU_1",
            document_code="LAW3",
            is_placeholder=True,
            chunk_id=None,
            document_id=None,
            document_name=None,
        )
    }
    result = _classify({}, related, [], document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.suggested_documents == [
        {
            "document_code": "LAW3",
            "document_id": None,
            "name": None,
            "in_library": False,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]
    assert result.citation_graph_path[0]["in_context"] is False


def test_classify_related_uses_min_hops_when_deduped_by_caller():
    # _classify chỉ nhận related_by_addr ĐÃ dedup (orchestrator giữ hops nhỏ nhất) —
    # test này xác nhận field hops truyền qua path đúng như trong row.
    related = {"owner_x:LAW2:DIEU_10": _related_row(hops=2)}
    result = _classify({}, related, [], document_ids=None)
    assert result.citation_graph_path[0]["hops"] == 2
    # score suy giảm theo hops (0.5**hops) — xác nhận không lỗi off-by-one.
    assert result.context_chunks[0].score == 0.25


# ── _classify: LegalDocument (VIEN_DAN_VAN_BAN) ───────────────────────────────


def _legal_doc_row(**overrides) -> dict:
    row = {
        "source_addr": "owner_x:LAW1:DIEU_5",
        "legal_address": "owner_x:LAW4",
        "document_code": "LAW4",
        "name": "Luật 4",
        "is_placeholder": False,
        "document_id": None,
        "document_name": None,
    }
    row.update(overrides)
    return row


def test_classify_legal_document_placeholder_becomes_suggestion():
    rows = [_legal_doc_row(is_placeholder=True)]
    result = _classify({}, {}, rows, document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.suggested_documents == [
        {
            "document_code": "LAW4",
            "document_id": None,
            "name": None,
            "in_library": False,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]
    # LegalDocument không bao giờ vào context (không có nội dung cấp Điều)
    assert result.citation_graph_path[0]["in_context"] is False


def test_classify_legal_document_real_not_in_scope_is_suggestion_in_library():
    rows = [_legal_doc_row(document_id="doc-D", document_name="Luật D trong thư viện")]
    result = _classify({}, {}, rows, document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.suggested_documents == [
        {
            "document_code": "LAW4",
            "document_id": "doc-D",
            "name": "Luật 4",
            "in_library": True,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]


def test_classify_legal_document_real_already_in_scope_skips_suggestion():
    # resolved_id nằm trong document_ids đã gắn -> không cần gợi ý (đã ở trong context
    # qua Provision anchor/related rồi).
    rows = [_legal_doc_row(document_id="doc-A")]
    result = _classify({}, {}, rows, document_ids=["doc-A"])

    assert result.suggested_documents == []


def test_classify_legal_document_unresolved_with_document_ids_none_is_suggestion():
    # document_id=None (chưa resolve được) -> _in_scope luôn False dù document_ids=None,
    # nên vẫn suggestion (in_library=False vì không có document_id resolve).
    rows = [_legal_doc_row(document_id=None)]
    result = _classify({}, {}, rows, document_ids=None)

    assert result.suggested_documents == [
        {
            "document_code": "LAW4",
            "document_id": None,
            "name": "Luật 4",
            "in_library": False,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]


# ── _classify: dedupe suggestions theo document_code ──────────────────────────


def test_classify_dedupes_suggestions_by_document_code_first_wins():
    related = {
        "owner_x:LAW2:DIEU_10": _related_row(),
        "owner_x:LAW2:DIEU_11": _related_row(
            legal_address="owner_x:LAW2:DIEU_11",
            chunk_id="chunk-3",
            hops=2,
        ),
    }
    result = _classify({}, related, [], document_ids=["doc-A"])

    # Cả 2 related Provision đều thuộc LAW2 (doc-B, ngoài phạm vi) -> chỉ 1 suggestion
    # duy nhất cho document_code LAW2 (giữ bản đầu tiên gặp).
    codes = [s["document_code"] for s in result.suggested_documents]
    assert codes == ["LAW2"]


# ── Full flow: mix anchor + related in-scope + related out-of-scope + legal doc ──


def test_classify_full_mix_matches_task_scenario():
    """Mirror kịch bản integration test: A viện dẫn B. A gắn vào hội thoại, B thì
    tuỳ case có/không nằm trong document_ids."""
    anchors = {
        "owner_x:A:DIEU_1": {
            "legal_address": "owner_x:A:DIEU_1",
            "document_code": "A",
            "content": "Điều 1 văn bản A",
            "chunk_id": "chunk-a1",
            "document_id": "doc-A",
            "document_name": "Văn bản A",
        }
    }
    related = {
        "owner_x:B:DIEU_2": _related_row(
            anchor_addr="owner_x:A:DIEU_1",
            legal_address="owner_x:B:DIEU_2",
            document_code="B",
            content="Điều 2 văn bản B",
            chunk_id="chunk-b2",
            document_id="doc-B",
            document_name="Văn bản B",
        )
    }

    # Case 1: cả A và B đều gắn vào hội thoại -> context có cả 2, không suggestion.
    both_attached = _classify(anchors, related, [], document_ids=["doc-A", "doc-B"])
    assert {c.chunk_id for c in both_attached.context_chunks} == {"chunk-a1", "chunk-b2"}
    assert both_attached.suggested_documents == []

    # Case 2: chỉ A gắn -> B rơi vào suggested_documents, KHÔNG vào context.
    only_a_attached = _classify(anchors, related, [], document_ids=["doc-A"])
    assert {c.chunk_id for c in only_a_attached.context_chunks} == {"chunk-a1"}
    assert only_a_attached.suggested_documents == [
        {
            "document_code": "B",
            "document_id": "doc-B",
            "name": "Văn bản B",
            "in_library": True,
            "cited_from": "owner_x:A:DIEU_1",
        }
    ]
