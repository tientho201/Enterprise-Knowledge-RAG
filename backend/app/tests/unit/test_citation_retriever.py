"""Unit test cho phần logic thuần (không cần Neo4j) của rag/citation_retriever.py:
_owner_clause, _in_scope, và bộ phân loại context-vs-suggestion _classify.

Test Neo4j-dependent (Cypher traversal thật) nằm ở
tests/integration/test_citation_retrieval.py (@pytest.mark.neo4j)."""

import inspect

import pytest

from app.rag.citation_retriever import (
    _classify,
    _format_node_label,
    _in_scope,
    _is_excluded,
    _owner_clause,
    graph_augmented_search,
)

# ── _format_node_label ─────────────────────────────────────────────────────────


def test_format_node_label_provision_dieu_only():
    assert _format_node_label(5, None, None, "Nghị định 88/2019", "ND88") == (
        "Điều 5, Nghị định 88/2019"
    )


def test_format_node_label_provision_dieu_khoan_diem():
    assert _format_node_label(5, 2, "a", "Nghị định 88/2019", "ND88") == (
        "Điều 5 Khoản 2 Điểm a, Nghị định 88/2019"
    )


def test_format_node_label_falls_back_to_document_code_without_name():
    assert _format_node_label(5, None, None, None, "ND88") == "Điều 5, ND88"


def test_format_node_label_legal_document_no_dieu_uses_name_only():
    assert _format_node_label(None, None, None, "Luật 4", "LAW4") == "Luật 4"
    assert _format_node_label(None, None, None, None, "LAW4") == "LAW4"


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


def _anchor_row(**overrides) -> dict:
    row = {
        "legal_address": "owner_x:LAW1:DIEU_5",
        "document_code": "LAW1",
        "content": "Nội dung Điều 5",
        "dieu": 5,
        "khoan": None,
        "diem": None,
        "chunk_id": "chunk-1",
        "document_id": "doc-A",
        "document_name": "Luật A",
    }
    row.update(overrides)
    return row


def test_classify_anchor_always_goes_to_context():
    anchors = {"owner_x:LAW1:DIEU_5": _anchor_row()}
    result = _classify(anchors, {}, [], document_ids=["doc-A"])

    assert len(result.context_chunks) == 1
    assert result.context_chunks[0].chunk_id == "chunk-1"
    assert result.context_chunks[0].document_id == "doc-A"
    assert result.suggested_documents == []
    assert result.citation_graph_path == []
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW1:DIEU_5",
            "label": "Điều 5, Luật A",
            "document_id": "doc-A",
            "document_name": "Luật A",
            "node_type": "anchor",
            "in_library": True,
            "content": "Nội dung Điều 5",
        }
    ]


def test_classify_anchor_in_context_even_when_document_ids_excludes_it():
    # Anchor đã owner/document-scoped từ _dense_search TRƯỚC khi tới traversal —
    # _classify không re-check document_ids cho anchor.
    anchors = {"owner_x:LAW1:DIEU_5": _anchor_row()}
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
        "dieu": 10,
        "khoan": None,
        "diem": None,
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
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW2:DIEU_10",
            "label": "Điều 10, Luật B",
            "document_id": "doc-B",
            "document_name": "Luật B",
            "node_type": "in_context",
            "in_library": True,
            "content": "Nội dung Điều 10 của Luật 2",
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
    # out_of_scope nhưng in_library=True (đã có trong thư viện owner, chưa gắn hội
    # thoại này) -> node vẫn mang document_id/name để FE gợi ý gắn, nhưng content=None.
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW2:DIEU_10",
            "label": "Điều 10, Luật B",
            "document_id": "doc-B",
            "document_name": "Luật B",
            "node_type": "out_of_scope",
            "in_library": True,
            "content": None,
        }
    ]


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
            dieu=1,
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
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW3:DIEU_1",
            "label": "Điều 1, LAW3",
            "document_id": None,
            "document_name": None,
            "node_type": "out_of_scope",
            "in_library": False,
            "content": None,
        }
    ]


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
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW4",
            "label": "LAW4",
            "document_id": None,
            "document_name": None,
            "node_type": "out_of_scope",
            "in_library": False,
            "content": None,
        }
    ]


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
    # Node label ưu tiên LegalDocument.name (graph) — mirror add_suggestion, KHÔNG
    # dùng document_name (Postgres-resolved) cho label hiển thị.
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW4",
            "label": "Luật 4",
            "document_id": "doc-D",
            "document_name": "Luật 4",
            "node_type": "out_of_scope",
            "in_library": True,
            "content": None,
        }
    ]


def test_classify_legal_document_real_already_in_scope_skips_suggestion():
    # resolved_id nằm trong document_ids đã gắn -> không cần gợi ý (đã ở trong context
    # qua Provision anchor/related rồi).
    rows = [_legal_doc_row(document_id="doc-A")]
    result = _classify({}, {}, rows, document_ids=["doc-A"])

    assert result.suggested_documents == []
    # Node registry KHÔNG dedup theo cùng logic "đã trong scope" của suggestion — edge
    # VIEN_DAN_VAN_BAN tới address này luôn tồn tại trong citation_graph_path nên FE
    # vẫn cần node để vẽ, dù không cần gợi ý gắn thêm.
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW4",
            "label": "Luật 4",
            "document_id": "doc-A",
            "document_name": "Luật 4",
            "node_type": "out_of_scope",
            "in_library": True,
            "content": None,
        }
    ]


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
    assert result.citation_graph_nodes == [
        {
            "address": "owner_x:LAW4",
            "label": "Luật 4",
            "document_id": None,
            "document_name": "Luật 4",
            "node_type": "out_of_scope",
            "in_library": False,
            "content": None,
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
    node_types = {n["address"]: n["node_type"] for n in both_attached.citation_graph_nodes}
    assert node_types == {"owner_x:A:DIEU_1": "anchor", "owner_x:B:DIEU_2": "in_context"}
    contents = {n["address"]: n["content"] for n in both_attached.citation_graph_nodes}
    assert contents == {
        "owner_x:A:DIEU_1": "Điều 1 văn bản A",
        "owner_x:B:DIEU_2": "Điều 2 văn bản B",
    }

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
    node_types_2 = {n["address"]: n["node_type"] for n in only_a_attached.citation_graph_nodes}
    assert node_types_2 == {"owner_x:A:DIEU_1": "anchor", "owner_x:B:DIEU_2": "out_of_scope"}
    # B out_of_scope -> content bị chặn dù đã biết nguyên văn (KHÔNG lộ nội dung tài
    # liệu chưa gắn vào hội thoại này qua đồ thị).
    b_node = next(
        n for n in only_a_attached.citation_graph_nodes if n["address"] == "owner_x:B:DIEU_2"
    )
    assert b_node["content"] is None


# ── Tài liệu đang tắt: _is_excluded / _in_scope ───────────────────────────────


def test_is_excluded_none_or_empty_excludes_nothing():
    assert _is_excluded("doc-1", None) is False
    assert _is_excluded("doc-1", []) is False
    assert _is_excluded(None, ["doc-1"]) is False


def test_is_excluded_matches_listed_document():
    assert _is_excluded("doc-1", ["doc-1"]) is True
    assert _is_excluded("doc-2", ["doc-1"]) is False


def test_in_scope_excluded_document_is_out_of_scope_when_unrestricted():
    # document_ids=None (cả thư viện) KHÔNG được mở lại tài liệu đang tắt.
    assert _in_scope("doc-1", None, ["doc-1"]) is False
    assert _in_scope("doc-2", None, ["doc-1"]) is True


def test_in_scope_excluded_wins_over_explicit_document_ids():
    # Client gửi đích danh ID tài liệu đang tắt trong document_ids vẫn bị loại.
    assert _in_scope("doc-1", ["doc-1", "doc-2"], ["doc-1"]) is False
    assert _in_scope("doc-2", ["doc-1", "doc-2"], ["doc-1"]) is True


def test_in_scope_exclusion_never_widens_document_ids():
    # Loại trừ chỉ thu hẹp: tài liệu ngoài document_ids vẫn ngoài phạm vi.
    assert _in_scope("doc-3", ["doc-1"], ["doc-9"]) is False
    assert _in_scope(None, None, ["doc-9"]) is False


@pytest.mark.parametrize("excluded", [None, []])
def test_in_scope_default_and_empty_exclusion_match_legacy_behaviour(excluded):
    for document_id in (None, "doc-1", "doc-3"):
        for document_ids in (None, [], ["doc-1", "doc-2"]):
            assert _in_scope(document_id, document_ids, excluded) == _in_scope(
                document_id, document_ids
            )


# ── Tài liệu đang tắt: _classify ──────────────────────────────────────────────


@pytest.mark.parametrize("document_ids", [None, ["doc-A", "doc-B"]])
def test_classify_related_of_excluded_document_not_in_context(document_ids):
    # doc-B đang tắt. Dù hội thoại không giới hạn tài liệu (None) hay gắn đích danh
    # doc-B, Provision của doc-B KHÔNG được vào context và KHÔNG lộ content.
    anchors = {"owner_x:LAW1:DIEU_5": _anchor_row()}
    related = {"owner_x:LAW2:DIEU_10": _related_row()}
    result = _classify(anchors, related, [], document_ids, excluded_document_ids=["doc-B"])

    assert [c.chunk_id for c in result.context_chunks] == ["chunk-1"]
    assert all(c.document_id != "doc-B" for c in result.context_chunks)
    assert "Nội dung Điều 10 của Luật 2" not in [c.content for c in result.context_chunks]
    assert result.citation_graph_path == [
        {
            "from_address": "owner_x:LAW1:DIEU_5",
            "to_address": "owner_x:LAW2:DIEU_10",
            "relation": "VIEN_DAN",
            "hops": 1,
            "in_context": False,
        }
    ]
    b_node = next(n for n in result.citation_graph_nodes if n["address"] == "owner_x:LAW2:DIEU_10")
    assert b_node["node_type"] == "out_of_scope"
    assert b_node["content"] is None
    # Vẫn là tài liệu của owner -> chỉ còn là gợi ý (metadata), giống tài liệu chưa gắn.
    assert result.suggested_documents == [
        {
            "document_code": "LAW2",
            "document_id": "doc-B",
            "name": "Luật B",
            "in_library": True,
            "cited_from": "owner_x:LAW1:DIEU_5",
        }
    ]


def test_classify_anchor_of_excluded_document_is_dropped_with_its_edges():
    # Defense-in-depth: anchor thuộc tài liệu đang tắt (dense search lọc sót) bị bỏ
    # hẳn, kéo theo mọi cạnh/related/legal doc xuất phát từ nó.
    anchors = {"owner_x:LAW1:DIEU_5": _anchor_row()}
    related = {"owner_x:LAW2:DIEU_10": _related_row()}
    legal = [_legal_doc_row()]
    result = _classify(anchors, related, legal, None, excluded_document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.citation_graph_path == []
    assert result.citation_graph_nodes == []
    assert result.suggested_documents == []


def test_classify_only_excluded_anchor_dropped_other_anchor_kept():
    anchors = {
        "owner_x:LAW1:DIEU_5": _anchor_row(),
        "owner_x:LAW5:DIEU_1": _anchor_row(
            legal_address="owner_x:LAW5:DIEU_1",
            document_code="LAW5",
            content="Nội dung tài liệu tắt",
            chunk_id="chunk-off",
            document_id="doc-OFF",
            document_name="Luật tắt",
        ),
    }
    result = _classify(anchors, {}, [], None, excluded_document_ids=["doc-OFF"])

    assert [c.chunk_id for c in result.context_chunks] == ["chunk-1"]
    assert [n["address"] for n in result.citation_graph_nodes] == ["owner_x:LAW1:DIEU_5"]


def test_classify_legal_document_resolving_to_excluded_document_is_not_in_scope():
    # LegalDocument resolve về tài liệu đang tắt: không được coi là "đã trong phạm vi"
    # (không có gì của nó ở trong context) -> vẫn là gợi ý; không bao giờ có content.
    rows = [_legal_doc_row(document_id="doc-A")]
    result = _classify({}, {}, rows, ["doc-A"], excluded_document_ids=["doc-A"])

    assert result.context_chunks == []
    assert [s["document_id"] for s in result.suggested_documents] == ["doc-A"]
    assert result.citation_graph_nodes[0]["content"] is None


@pytest.mark.parametrize("excluded", [None, []])
@pytest.mark.parametrize("document_ids", [None, ["doc-A"], ["doc-A", "doc-B"]])
def test_classify_default_and_empty_exclusion_match_legacy_behaviour(document_ids, excluded):
    anchors = {"owner_x:LAW1:DIEU_5": _anchor_row()}
    related = {
        "owner_x:LAW2:DIEU_10": _related_row(),
        "owner_x:LAW3:DIEU_1": _related_row(
            legal_address="owner_x:LAW3:DIEU_1",
            document_code="LAW3",
            is_placeholder=True,
            chunk_id=None,
            document_id=None,
            document_name=None,
        ),
    }
    legal = [_legal_doc_row(), _legal_doc_row(legal_address="owner_x:LAW6", document_id="doc-A")]

    legacy = _classify(anchors, related, legal, document_ids)
    assert _classify(anchors, related, legal, document_ids, excluded) == legacy
    assert (
        _classify(anchors, related, legal, document_ids, excluded_document_ids=excluded) == legacy
    )


# ── Tài liệu đang tắt: graph_augmented_search (Neo4j giả, không cần dịch vụ thật) ──


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def data(self) -> list[dict]:
        return self._rows


class _FakeSession:
    """Trả kết quả theo loại truy vấn và ghi lại (cypher, params) của mọi lời gọi."""

    def __init__(self, anchor_rows, related_rows, legal_rows):
        self._anchor_rows = anchor_rows
        self._related_rows = related_rows
        self._legal_rows = legal_rows
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, cypher: str, **params) -> _FakeResult:
        self.calls.append((cypher, params))
        if "seed_chunk" in cypher:
            return _FakeResult(self._anchor_rows)
        if "VIEN_DAN_VAN_BAN" in cypher:
            return _FakeResult(self._legal_rows)
        return _FakeResult(self._related_rows)


class _FakeDriver:
    def __init__(self, session: _FakeSession):
        self._session = session

    def session(self) -> _FakeSession:
        return self._session


@pytest.fixture
def fake_neo4j(monkeypatch):
    def _install(anchor_rows, related_rows=(), legal_rows=()) -> _FakeSession:
        session = _FakeSession(list(anchor_rows), list(related_rows), list(legal_rows))
        monkeypatch.setattr("app.rag.graph_client.get_neo4j_driver", lambda: _FakeDriver(session))
        return session

    return _install


def test_graph_augmented_search_signature_keeps_positional_order():
    # test integration và agents/retriever.py gọi 3 tham số đầu theo vị trí; tham số
    # mới phải là keyword-only và mặc định None (không truyền = hành vi cũ).
    params = inspect.signature(graph_augmented_search).parameters
    assert list(params) == ["seed_chunk_ids", "document_ids", "owner_id", "excluded_document_ids"]
    assert params["excluded_document_ids"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["excluded_document_ids"].default is None


def test_graph_augmented_search_excluded_related_provision_not_in_context(fake_neo4j):
    session = fake_neo4j([_anchor_row()], [_related_row()])

    result = graph_augmented_search(["chunk-1"], None, "owner-1", excluded_document_ids=["doc-B"])

    assert [c.chunk_id for c in result.context_chunks] == ["chunk-1"]
    assert all(c.document_id != "doc-B" for c in result.context_chunks)
    b_node = next(n for n in result.citation_graph_nodes if n["address"] == "owner_x:LAW2:DIEU_10")
    assert b_node["content"] is None
    # Provision của tài liệu tắt không làm nguồn mở rộng VIEN_DAN_VAN_BAN: cả địa chỉ
    # Provision lẫn LegalDocument của văn bản chứa nó (LAW2) đều không được truy vấn.
    legal_addrs = [
        addr for cypher, p in session.calls if "VIEN_DAN_VAN_BAN" in cypher for addr in p["addrs"]
    ]
    assert legal_addrs
    assert not any("LAW2" in addr for addr in legal_addrs)


def test_graph_augmented_search_excluded_anchor_stops_traversal(fake_neo4j):
    # Seed thuộc tài liệu tắt -> kết quả rỗng và KHÔNG chạy truy vấn mở rộng nào.
    session = fake_neo4j([_anchor_row()], [_related_row()], [_legal_doc_row()])

    result = graph_augmented_search(["chunk-1"], None, "owner-1", excluded_document_ids=["doc-A"])

    assert result.context_chunks == []
    assert result.citation_graph_path == []
    assert result.citation_graph_nodes == []
    assert result.suggested_documents == []
    assert len(session.calls) == 1


def test_graph_augmented_search_mixed_anchors_only_traverses_from_active(fake_neo4j):
    off_anchor = _anchor_row(
        legal_address="owner_x:LAW5:DIEU_1",
        document_code="LAW5",
        chunk_id="chunk-off",
        document_id="doc-OFF",
    )
    session = fake_neo4j([_anchor_row(), off_anchor])

    result = graph_augmented_search(
        ["chunk-1", "chunk-off"], None, "owner-1", excluded_document_ids=["doc-OFF"]
    )

    assert [c.chunk_id for c in result.context_chunks] == ["chunk-1"]
    assert len(session.calls) > 1
    for cypher, params in session.calls[1:]:
        sources = params.get("anchors") or params.get("addrs")
        assert not any("LAW5" in addr for addr in sources), cypher


@pytest.mark.parametrize("owner_id", ["owner-1", None])
def test_graph_augmented_search_exclusion_keeps_owner_filter(fake_neo4j, owner_id):
    # Thêm loại trừ KHÔNG được nới filter owner_id: mọi truy vấn vẫn nhận đúng
    # owner_id và (với non-admin) vẫn chứa mệnh đề owner_id trong Cypher.
    with_exclusion = fake_neo4j([_anchor_row()], [_related_row()])
    graph_augmented_search(["chunk-1"], None, owner_id, excluded_document_ids=["doc-B"])
    without = fake_neo4j([_anchor_row()], [_related_row()])
    graph_augmented_search(["chunk-1"], None, owner_id)

    assert len(with_exclusion.calls) == 4
    for cypher, params in with_exclusion.calls:
        assert params["owner_id"] == owner_id
        assert ("owner_id = $owner_id" in cypher) is (owner_id is not None)
    # Cypher không đổi theo tham số mới — loại trừ chỉ thu hẹp ở bước hậu xử lý.
    assert [c for c, _ in with_exclusion.calls] == [c for c, _ in without.calls]


@pytest.mark.parametrize("excluded", [None, []])
def test_graph_augmented_search_default_matches_legacy_behaviour(fake_neo4j, excluded):
    rows = ([_anchor_row()], [_related_row()], [_legal_doc_row()])
    legacy_session = fake_neo4j(*rows)
    legacy = graph_augmented_search(["chunk-1"], ["doc-A", "doc-B"], "owner-1")
    session = fake_neo4j(*rows)
    result = graph_augmented_search(
        ["chunk-1"], ["doc-A", "doc-B"], "owner-1", excluded_document_ids=excluded
    )

    assert result == legacy
    assert {c.chunk_id for c in result.context_chunks} == {"chunk-1", "chunk-2"}
    assert session.calls == legacy_session.calls
