"""
`HybridRetriever.merge()` — bước trộn điểm dense + graph, tách khỏi `retrieve()`.

Ba nhóm kiểm:
1. Hợp đồng của `merge()`: công thức 0.7/0.3, chunk chỉ-ở-graph, thứ tự, đầu vào rỗng,
   chuẩn hoá khi điểm 0/âm, chốt chặn loại trừ.
2. Tính thuần: không sửa tại chỗ `dense_results` / `graph_results`, gọi lại cho cùng
   kết quả, không chạm mạng.
3. Tương đương cũ/mới: `_legacy_merge` là BẢN SAO NGUYÊN VĂN đoạn "Merge & rank" cũ của
   `retrieve()` (bản sửa tại chỗ). `merge()` và `retrieve()` (Qdrant/Neo4j giả) phải cho
   đúng id, đúng thứ tự, đúng từng số thực như bản cũ.

Trọng số luôn truyền tường minh (0.7/0.3) để test không phụ thuộc `backend/.env`.
"""

import copy
import inspect
import random

import pytest

from app.rag.retriever import HybridRetriever, RetrievedChunk

GraphResults = dict[str, tuple[RetrievedChunk, float]]


def _retriever(dense_weight: float = 0.7, graph_weight: float = 0.3) -> HybridRetriever:
    return HybridRetriever(dense_weight=dense_weight, graph_weight=graph_weight)


def _chunk(chunk_id: str, score: float, document_id: str = "d1", chunk_index: int = 0):
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"{document_id}.pdf",
        content=f"content of {chunk_id}",
        score=score,
        chunk_index=chunk_index,
    )


def _graph(*entries: tuple[str, float, str]) -> GraphResults:
    """(chunk_id, graph_score, document_id) → dict đúng hình dạng `_graph_search` trả về."""
    return {
        cid: (_chunk(cid, score, document_id, chunk_index=1), score)
        for cid, score, document_id in entries
    }


def _legacy_merge(
    dense_results: list[RetrievedChunk],
    graph_results: GraphResults,
    dense_weight: float,
    graph_weight: float,
    excluded_document_ids: list[str] | None = None,
) -> list[RetrievedChunk]:
    """Oracle: đoạn "Merge & rank" cũ của `retrieve()`, chép nguyên văn (SỬA TẠI CHỖ).

    Chỉ dùng trên bản sao của đầu vào. Đừng "dọn" hàm này: giá trị của nó là giữ đúng
    từng phép tính của bản cũ để so từng số thực.
    """
    if not dense_results:
        return []

    max_dense = max(r.score for r in dense_results) or 1.0

    merged: dict[str, RetrievedChunk] = {}

    for chunk in dense_results:
        norm_dense = chunk.score / max_dense
        _, graph_score = graph_results.get(chunk.chunk_id, (None, 0.0))
        chunk.score = dense_weight * norm_dense + graph_weight * graph_score
        merged[chunk.chunk_id] = chunk

    for chunk_id, (chunk, graph_score) in graph_results.items():
        if chunk_id not in merged:
            chunk.score = graph_weight * graph_score
            merged[chunk_id] = chunk

    if excluded_document_ids:
        excluded = set(excluded_document_ids)
        for chunk_id in [cid for cid, c in merged.items() if c.document_id in excluded]:
            del merged[chunk_id]

    return sorted(merged.values(), key=lambda x: x.score, reverse=True)


def _rows(chunks: list[RetrievedChunk]) -> list[tuple]:
    """Mọi field, điểm ở dạng repr → so khớp TUYỆT ĐỐI từng bit số thực, đúng thứ tự."""
    return [
        (c.chunk_id, c.document_id, c.document_name, c.content, repr(c.score), c.chunk_index)
        for c in chunks
    ]


# ── 1. Hợp đồng của merge() ──────────────────────────────────────────────────


class TestMergeFormula:
    def test_dense_plus_graph_boost_uses_07_03(self):
        dense = [_chunk("a", 0.8), _chunk("b", 0.4)]
        graph = _graph(("b", 1.0, "d1"), ("a", 0.5, "d1"))

        merged = _retriever().merge(dense, graph)

        by_id = {c.chunk_id: c.score for c in merged}
        # max_dense = 0.8 → norm a = 1.0, norm b = 0.5
        assert by_id["a"] == pytest.approx(0.7 * 1.0 + 0.3 * 0.5)
        assert by_id["b"] == pytest.approx(0.7 * 0.5 + 0.3 * 1.0)
        assert [c.chunk_id for c in merged] == ["a", "b"]

    def test_dense_without_graph_entry_gets_zero_graph_score(self):
        merged = _retriever().merge([_chunk("a", 0.9), _chunk("b", 0.45)], {})

        assert [(c.chunk_id, c.score) for c in merged] == [
            ("a", pytest.approx(0.7)),
            ("b", pytest.approx(0.35)),
        ]

    def test_graph_only_chunk_gets_graph_weight_times_graph_score(self):
        dense = [_chunk("a", 0.9)]
        graph = _graph(("g1", 1.0, "d2"), ("g2", 0.25, "d2"))

        merged = _retriever().merge(dense, graph)

        by_id = {c.chunk_id: c for c in merged}
        assert by_id["g1"].score == pytest.approx(0.3 * 1.0)
        assert by_id["g2"].score == pytest.approx(0.3 * 0.25)
        # chunk chỉ-ở-graph giữ nguyên nội dung/metadata của node graph
        assert by_id["g1"].document_id == "d2"
        assert by_id["g1"].content == "content of g1"
        assert by_id["g1"].chunk_index == 1

    def test_graph_score_comes_from_tuple_not_from_chunk_score(self):
        # Bản cũ đọc số trong tuple, không đọc chunk.score của node graph.
        graph: GraphResults = {"g": (_chunk("g", 0.99, "d2"), 0.5)}

        merged = _retriever().merge([_chunk("a", 1.0)], graph)

        assert {c.chunk_id: c.score for c in merged}["g"] == pytest.approx(0.3 * 0.5)

    def test_chunk_in_both_keeps_dense_copy_metadata(self):
        dense = [_chunk("a", 0.9, document_id="dense-doc", chunk_index=7)]
        graph = _graph(("a", 1.0, "graph-doc"))

        (only,) = _retriever().merge(dense, graph)

        assert only.document_id == "dense-doc"
        assert only.chunk_index == 7
        assert only.score == pytest.approx(0.7 + 0.3)

    def test_uses_instance_weights(self):
        dense = [_chunk("a", 1.0), _chunk("b", 0.5)]
        graph = _graph(("b", 1.0, "d1"), ("g", 1.0, "d2"))

        merged = _retriever(dense_weight=0.2, graph_weight=0.8).merge(dense, graph)

        assert {c.chunk_id: c.score for c in merged} == {
            "a": pytest.approx(0.2),
            "b": pytest.approx(0.2 * 0.5 + 0.8),
            "g": pytest.approx(0.8),
        }
        assert [c.chunk_id for c in merged] == ["b", "g", "a"]


class TestMergeOrdering:
    def test_sorted_by_descending_score(self):
        dense = [_chunk("low", 0.1), _chunk("high", 0.9), _chunk("mid", 0.5)]
        graph = _graph(("g", 1.0, "d2"))

        merged = _retriever().merge(dense, graph)

        scores = [c.score for c in merged]
        assert scores == sorted(scores, reverse=True)
        assert [c.chunk_id for c in merged] == ["high", "mid", "g", "low"]

    def test_ties_keep_input_order_dense_first_then_graph_only(self):
        # a, b, c cùng 0.7; g1, g2 cùng 0.3 → sort ổn định giữ thứ tự chèn.
        dense = [_chunk("a", 0.5), _chunk("b", 0.5), _chunk("c", 0.5)]
        graph = _graph(("g1", 1.0, "d2"), ("g2", 1.0, "d2"))

        merged = _retriever().merge(dense, graph)

        assert [c.chunk_id for c in merged] == ["a", "b", "c", "g1", "g2"]

    def test_tie_between_dense_and_graph_only_keeps_dense_first(self):
        # dense "b": 0.5 * (0.5 / 1.0) = 0.25 ; graph-only "g": 0.5 * 0.5 = 0.25
        dense = [_chunk("a", 1.0), _chunk("b", 0.5)]
        graph = _graph(("g", 0.5, "d2"))

        merged = _retriever(dense_weight=0.5, graph_weight=0.5).merge(dense, graph)

        assert merged[1].score == merged[2].score == 0.25
        assert [c.chunk_id for c in merged] == ["a", "b", "g"]

    def test_duplicate_dense_ids_last_one_wins_at_first_position(self):
        # Hành vi cũ của dict: giá trị lấy bản xuất hiện SAU, vị trí giữ của bản ĐẦU.
        dense = [_chunk("a", 0.5), _chunk("b", 0.5), _chunk("a", 1.0, chunk_index=9)]

        merged = _retriever().merge(dense, {})

        assert [(c.chunk_id, c.chunk_index) for c in merged] == [("a", 9), ("b", 0)]
        assert merged[0].score == pytest.approx(0.7)


class TestMergeEdgeInputs:
    def test_empty_dense_returns_empty_list(self):
        assert _retriever().merge([], {}) == []

    def test_empty_dense_returns_empty_even_with_graph_results(self):
        # retrieve() cũ trả [] ngay khi dense rỗng (không có seed) → merge() giữ đúng thế.
        assert _retriever().merge([], _graph(("g", 1.0, "d2"))) == []

    def test_empty_graph_is_dense_only(self):
        merged = _retriever().merge([_chunk("a", 0.6), _chunk("b", 0.3)], {})

        assert [(c.chunk_id, c.score) for c in merged] == [
            ("a", pytest.approx(0.7)),
            ("b", pytest.approx(0.35)),
        ]

    def test_single_chunk_normalises_to_dense_weight(self):
        (only,) = _retriever().merge([_chunk("a", 0.42)], {})

        assert only.score == pytest.approx(0.7)

    def test_all_zero_dense_scores_do_not_divide_by_zero(self):
        # max_dense = 0 → dùng 1.0; điểm dense chuẩn hoá = 0.
        dense = [_chunk("a", 0.0), _chunk("b", 0.0)]
        graph = _graph(("b", 1.0, "d1"), ("g", 0.5, "d2"))

        merged = _retriever().merge(dense, graph)

        assert {c.chunk_id: c.score for c in merged} == {
            "a": 0.0,
            "b": pytest.approx(0.3),
            "g": pytest.approx(0.15),
        }
        assert [c.chunk_id for c in merged] == ["b", "g", "a"]

    def test_single_zero_score_chunk(self):
        (only,) = _retriever().merge([_chunk("a", 0.0)], {})

        assert only.score == 0.0

    def test_negative_dense_scores_keep_legacy_normalisation(self):
        # Khoá hành vi CŨ (không phải hành vi mong muốn): max_dense âm → chia cho số âm
        # làm ĐẢO thứ hạng: chunk kém nhất (-0.8) lên đầu. Ngoài phạm vi sửa của task.
        dense = [_chunk("a", -0.2), _chunk("b", -0.8)]

        merged = _retriever().merge(dense, {})

        assert [(c.chunk_id, c.score) for c in merged] == [
            ("b", pytest.approx(0.7 * 4.0)),
            ("a", pytest.approx(0.7)),
        ]

    def test_zero_graph_score(self):
        merged = _retriever().merge([_chunk("a", 1.0)], _graph(("a", 0.0, "d1"), ("g", 0.0, "d2")))

        assert [(c.chunk_id, c.score) for c in merged] == [("a", pytest.approx(0.7)), ("g", 0.0)]


class TestMergeExclusionBackstop:
    """Chốt chặn loại trừ (T6) nằm TRONG merge(): gọi thẳng merge() không vòng qua được."""

    def test_excluded_document_dropped_from_dense_and_graph(self):
        dense = [_chunk("a", 0.9, "d1"), _chunk("x", 0.95, "d9")]
        graph = _graph(("gx", 1.0, "d9"), ("g", 0.5, "d2"))

        merged = _retriever().merge(dense, graph, excluded_document_ids=["d9"])

        assert [c.chunk_id for c in merged] == ["a", "g"]
        assert all(c.document_id != "d9" for c in merged)

    def test_excluded_chunk_still_counts_in_max_dense(self):
        # Hành vi cũ: chuẩn hoá TRƯỚC, loại trừ SAU → "a" = 0.7 * (0.5 / 1.0), không phải 0.7.
        dense = [_chunk("x", 1.0, "d9"), _chunk("a", 0.5, "d1")]

        (only,) = _retriever().merge(dense, {}, excluded_document_ids=["d9"])

        assert only.chunk_id == "a"
        assert only.score == pytest.approx(0.35)

    def test_everything_excluded_returns_empty(self):
        merged = _retriever().merge(
            [_chunk("x", 0.9, "d9")], _graph(("gx", 1.0, "d9")), excluded_document_ids=["d9"]
        )

        assert merged == []

    @pytest.mark.parametrize("excluded", [None, []])
    def test_none_or_empty_excludes_nothing(self, excluded):
        dense = [_chunk("a", 0.9, "d1"), _chunk("x", 0.5, "d9")]

        merged = _retriever().merge(dense, {}, excluded_document_ids=excluded)

        assert [c.chunk_id for c in merged] == ["a", "x"]
        assert _rows(merged) == _rows(_retriever().merge(dense, {}))

    def test_excluded_is_keyword_only(self):
        params = inspect.signature(HybridRetriever.merge).parameters

        assert list(params) == ["self", "dense_results", "graph_results", "excluded_document_ids"]
        assert params["excluded_document_ids"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["excluded_document_ids"].default is None

    def test_excluded_list_not_mutated(self):
        excluded = ["d9"]

        _retriever().merge([_chunk("x", 0.9, "d9")], {}, excluded_document_ids=excluded)

        assert excluded == ["d9"]


# ── 2. Tính thuần ────────────────────────────────────────────────────────────


class TestMergeIsPure:
    def _inputs(self) -> tuple[list[RetrievedChunk], GraphResults]:
        dense = [_chunk("a", 0.9), _chunk("b", 0.45), _chunk("x", 0.6, "d9")]
        graph = _graph(("b", 1.0, "d1"), ("g", 0.5, "d2"), ("gx", 0.25, "d9"))
        return dense, graph

    def test_input_chunk_scores_unchanged(self):
        dense, graph = self._inputs()

        _retriever().merge(dense, graph)

        assert [c.score for c in dense] == [0.9, 0.45, 0.6]
        assert {cid: (c.score, s) for cid, (c, s) in graph.items()} == {
            "b": (1.0, 1.0),
            "g": (0.5, 0.5),
            "gx": (0.25, 0.25),
        }

    def test_inputs_deep_equal_before_and_after(self):
        dense, graph = self._inputs()
        dense_before, graph_before = copy.deepcopy(dense), copy.deepcopy(graph)
        dense_objs = [id(c) for c in dense]
        graph_objs = {cid: id(c) for cid, (c, _) in graph.items()}

        _retriever().merge(dense, graph, excluded_document_ids=["d9"])

        # không đổi field nào, không thêm/bớt/đổi chỗ phần tử, vẫn là đúng các object cũ
        assert dense == dense_before
        assert graph == graph_before
        assert list(graph) == list(graph_before)
        assert [id(c) for c in dense] == dense_objs
        assert {cid: id(c) for cid, (c, _) in graph.items()} == graph_objs

    def test_returned_chunks_are_copies_not_input_objects(self):
        dense, graph = self._inputs()
        input_ids = {id(c) for c in dense} | {id(c) for c, _ in graph.values()}

        merged = _retriever().merge(dense, graph)

        assert len(merged) == 5
        assert all(id(c) not in input_ids for c in merged)
        assert all(isinstance(c, RetrievedChunk) for c in merged)

    def test_mutating_output_does_not_touch_inputs(self):
        dense, graph = self._inputs()

        merged = _retriever().merge(dense, graph)
        for c in merged:
            c.score = -1.0
            c.content = "changed"

        assert [c.score for c in dense] == [0.9, 0.45, 0.6]
        assert all(c.content.startswith("content of ") for c in dense)
        assert all(c.content.startswith("content of ") for c, _ in graph.values())

    def test_calling_twice_gives_identical_result(self):
        # Chính là lỗi task muốn tránh: bản sửa tại chỗ chuẩn hoá lại điểm ĐÃ trộn ở lần 2.
        dense, graph = self._inputs()
        retriever = _retriever()

        first = _rows(retriever.merge(dense, graph))
        second = _rows(retriever.merge(dense, graph))
        third = _rows(retriever.merge(dense, graph))

        assert first == second == third

    def test_legacy_in_place_version_was_not_idempotent(self):
        # Chứng minh test idempotent ở trên có sức bắt lỗi: oracle cũ cho kết quả KHÁC ở lần 2.
        dense, graph = self._inputs()

        first = _rows(_legacy_merge(dense, graph, 0.7, 0.3))
        second = _rows(_legacy_merge(dense, graph, 0.7, 0.3))

        assert first != second

    def test_same_object_twice_in_dense_is_scored_from_raw_score(self):
        # Khác biệt CÓ CHỦ Ý duy nhất với bản cũ: cùng MỘT object xuất hiện 2 lần trong
        # dense_results. Bản cũ sửa tại chỗ nên lần lặp thứ hai chuẩn hoá điểm đã trộn
        # (0.7 * (0.7/1.0) = 0.49); merge() luôn tính từ điểm thô (0.7). `_dense_search`
        # tạo object mới cho mỗi hit nên retrieve() không bao giờ gặp trường hợp này.
        shared = _chunk("a", 1.0)

        (only,) = _retriever().merge([shared, shared], {})

        assert only.score == pytest.approx(0.7)
        assert shared.score == 1.0

    def test_merge_is_sync_and_touches_no_network(self, monkeypatch):
        import httpx

        import app.rag.graph_client as graph_client

        def _boom(*a, **k):
            raise AssertionError("merge() không được chạm mạng")

        retriever = _retriever()
        monkeypatch.setattr(httpx, "Client", _boom)
        monkeypatch.setattr(graph_client, "get_neo4j_driver", _boom)
        monkeypatch.setattr(retriever, "_dense_search", _boom)
        monkeypatch.setattr(retriever, "_graph_search", _boom)
        monkeypatch.setattr(retriever, "_qdrant", None)
        dense, graph = self._inputs()

        merged = retriever.merge(dense, graph)

        assert not inspect.iscoroutinefunction(HybridRetriever.merge)
        assert isinstance(merged, list)
        assert len(merged) == 5


# ── 3. Tương đương cũ / mới ──────────────────────────────────────────────────


def _hit(chunk_id: str, document_id: str, score: float) -> dict:
    return {
        "id": chunk_id,
        "score": score,
        "payload": {
            "document_id": document_id,
            "document_name": f"{document_id}.pdf",
            "content": f"content of {chunk_id}",
            "chunk_index": 0,
        },
    }


def _record(chunk_id: str, document_id: str, connections: int) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": f"{document_id}.pdf",
        "content": f"graph content of {chunk_id}",
        "chunk_index": 1,
        "connections": connections,
    }


# (hits Qdrant, records Neo4j, excluded_document_ids)
_CASES: dict[str, tuple[list[dict], list[dict], list[str] | None]] = {
    "dense_empty": ([], [_record("g1", "d1", 3)], None),
    "graph_empty": ([_hit("a", "d1", 0.9), _hit("b", "d1", 0.5)], [], None),
    "overlap_both": (
        [_hit("a", "d1", 0.9), _hit("b", "d2", 0.5)],
        [_record("b", "d2", 4), _record("g", "d3", 2)],
        None,
    ),
    "graph_only": (
        [_hit("a", "d1", 0.8)],
        [_record("g1", "d2", 5), _record("g2", "d2", 1)],
        None,
    ),
    "ties": (
        [_hit("a", "d1", 0.5), _hit("b", "d1", 0.5), _hit("c", "d1", 0.5)],
        [_record("g1", "d2", 1), _record("g2", "d2", 1)],
        None,
    ),
    "tie_dense_vs_graph": (
        [_hit("a", "d1", 1.0), _hit("b", "d1", 3 / 7)],
        [_record("g1", "d2", 1)],
        None,
    ),
    "all_zero": ([_hit("a", "d1", 0.0), _hit("b", "d1", 0.0)], [_record("g1", "d2", 2)], None),
    "single": ([_hit("a", "d1", 0.42)], [], None),
    "single_zero": ([_hit("a", "d1", 0.0)], [], None),
    "negative": (
        [_hit("a", "d1", -0.2), _hit("b", "d1", -0.8)],
        [_record("b", "d1", 1), _record("g", "d2", 1)],
        None,
    ),
    "mixed_sign": (
        [_hit("a", "d1", 0.6), _hit("b", "d1", -0.3), _hit("c", "d1", 0.0)],
        [_record("c", "d1", 2), _record("g", "d2", 1)],
        None,
    ),
    "duplicate_dense_ids": (
        [_hit("a", "d1", 0.9), _hit("b", "d1", 0.7), _hit("a", "d1", 0.3)],
        [_record("a", "d1", 1)],
        None,
    ),
    "zero_connections": (
        [_hit("a", "d1", 0.9)],
        [_record("g1", "d2", 0), _record("g2", "d2", 0)],
        None,
    ),
    "excluded_leak": (
        [_hit("a", "d1", 0.9), _hit("x", "d9", 0.95), _hit("b", "d2", 0.4)],
        [_record("gx", "d9", 5), _record("g", "d2", 2), _record("a", "d1", 1)],
        ["d9"],
    ),
    "excluded_all": ([_hit("x", "d9", 0.9)], [_record("gx", "d9", 5)], ["d9"]),
    "excluded_empty_list": ([_hit("a", "d1", 0.9)], [_record("g", "d9", 5)], []),
}


def _random_case(rng: random.Random) -> tuple[list[dict], list[dict], list[str] | None]:
    ids = [f"c{i}" for i in range(12)]  # ít id → hay trùng giữa dense và graph
    docs = [f"d{i}" for i in range(4)]
    hits = [
        _hit(
            rng.choice(ids),
            rng.choice(docs),
            rng.choice([0.0, 0.5, 1.0, rng.uniform(-1, 1), rng.random()]),
        )
        for _ in range(rng.randint(0, 8))
    ]
    records = [
        _record(rng.choice(ids), rng.choice(docs), rng.randint(0, 5))
        for _ in range(rng.randint(0, 6))
    ]
    return hits, records, rng.choice([None, None, ["d0"], ["d1", "d3"]])


def _patch_backends(monkeypatch, hits: list[dict], records: list[dict]) -> dict:
    """Qdrant (httpx) + Neo4j driver giả. Trả dict đếm số lần mỗi backend được gọi."""
    calls = {"qdrant": 0, "neo4j": 0}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"result": hits}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):  # noqa: A002 - match httpx signature
            calls["qdrant"] += 1
            return _FakeResponse()

    class _FakeResult:
        @staticmethod
        def data():
            return records

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, query, **params):
            calls["neo4j"] += 1
            return _FakeResult()

    class _FakeDriver:
        @staticmethod
        def session():
            return _FakeSession()

    import httpx

    import app.rag.graph_client as graph_client

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(graph_client, "get_neo4j_driver", lambda: _FakeDriver())
    return calls


def _legacy_retrieve(
    retriever: HybridRetriever, excluded: list[str] | None
) -> list[RetrievedChunk]:
    """retrieve() CŨ: cùng `_dense_search` / `_graph_search` thật, rồi trộn bằng oracle."""
    dense = retriever._dense_search([0.1, 0.2, 0.3], None, "user-a", excluded_document_ids=excluded)
    if not dense:
        return []
    graph = retriever._graph_search(
        [r.chunk_id for r in dense], None, "user-a", excluded_document_ids=excluded
    )
    return _legacy_merge(dense, graph, retriever.dense_weight, retriever.graph_weight, excluded)


def _assert_retrieve_matches_legacy(monkeypatch, case, dense_weight=0.7, graph_weight=0.3):
    hits, records, excluded = case
    _patch_backends(monkeypatch, hits, records)
    retriever = _retriever(dense_weight, graph_weight)

    expected = _rows(_legacy_retrieve(retriever, excluded))
    actual = _rows(
        retriever.retrieve("q", [0.1, 0.2, 0.3], owner_id="user-a", excluded_document_ids=excluded)
    )

    assert actual == expected


class TestRetrieveEquivalentToLegacy:
    @pytest.mark.parametrize("name", sorted(_CASES))
    def test_retrieve_matches_legacy_formula(self, monkeypatch, name):
        _assert_retrieve_matches_legacy(monkeypatch, _CASES[name])

    @pytest.mark.parametrize("name", sorted(_CASES))
    def test_merge_matches_legacy_formula(self, monkeypatch, name):
        hits, records, excluded = _CASES[name]
        _patch_backends(monkeypatch, hits, records)
        retriever = _retriever()
        dense = retriever._dense_search([0.1], None, "user-a")
        graph = retriever._graph_search([r.chunk_id for r in dense], None, "user-a")

        expected = _rows(
            _legacy_merge(copy.deepcopy(dense), copy.deepcopy(graph), 0.7, 0.3, excluded)
        )
        actual = _rows(retriever.merge(dense, graph, excluded_document_ids=excluded))

        assert actual == expected

    def test_randomised_inputs_match_legacy(self, monkeypatch):
        rng = random.Random(20261010)
        for i in range(300):
            case = _random_case(rng)
            weights = (rng.choice([0.7, 0.5, 1.0]), rng.choice([0.3, 0.5, 1.0]))
            with monkeypatch.context() as m:
                try:
                    _assert_retrieve_matches_legacy(m, case, *weights)
                except AssertionError as exc:  # pragma: no cover - chỉ chạy khi lệch
                    raise AssertionError(f"case #{i} lệch: {case!r} weights={weights}") from exc

    def test_non_default_weights_match_legacy(self, monkeypatch):
        _assert_retrieve_matches_legacy(monkeypatch, _CASES["overlap_both"], 0.55, 0.45)


class TestRetrieveStillWiredCorrectly:
    def test_retrieve_signature_unchanged(self):
        params = inspect.signature(HybridRetriever.retrieve).parameters

        assert list(params) == [
            "self",
            "query",
            "query_embedding",
            "document_ids",
            "owner_id",
            "score_threshold",
            "excluded_document_ids",
        ]
        assert params["excluded_document_ids"].kind is inspect.Parameter.KEYWORD_ONLY
        assert all(
            params[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
            for name in ("query", "query_embedding", "document_ids", "owner_id", "score_threshold")
        )
        assert not inspect.iscoroutinefunction(HybridRetriever.retrieve)

    def test_retrieve_calls_each_backend_once_and_delegates_to_merge(self, monkeypatch):
        hits, records, _ = _CASES["overlap_both"]
        calls = _patch_backends(monkeypatch, hits, records)
        retriever = _retriever()
        seen: list[tuple] = []
        real_merge = retriever.merge

        def _spy(dense_results, graph_results, **kwargs):
            seen.append((list(dense_results), dict(graph_results), kwargs))
            return real_merge(dense_results, graph_results, **kwargs)

        monkeypatch.setattr(retriever, "merge", _spy)

        results = retriever.retrieve(
            "q", [0.1, 0.2, 0.3], owner_id="user-a", excluded_document_ids=["d9"]
        )

        assert calls == {"qdrant": 1, "neo4j": 1}
        assert len(seen) == 1
        dense_seen, graph_seen, kwargs = seen[0]
        assert [c.chunk_id for c in dense_seen] == ["a", "b"]
        assert set(graph_seen) == {"b", "g"}
        # chốt chặn loại trừ được chuyển nguyên vào merge()
        assert kwargs == {"excluded_document_ids": ["d9"]}
        assert [c.chunk_id for c in results] == ["a", "b", "g"]

    def test_retrieve_empty_dense_skips_graph_and_merge(self, monkeypatch):
        calls = _patch_backends(monkeypatch, [], [_record("g", "d1", 1)])
        retriever = _retriever()

        def _boom(*a, **k):
            raise AssertionError("dense rỗng thì không được gọi merge()")

        monkeypatch.setattr(retriever, "merge", _boom)

        assert retriever.retrieve("q", [0.1, 0.2, 0.3], owner_id="user-a") == []
        assert calls == {"qdrant": 1, "neo4j": 0}

    def test_retrieve_drops_excluded_chunk_that_leaked_past_db_filters(self, monkeypatch):
        # Khoá chốt chặn T6 ở mức retrieve(): backend giả BỎ QUA filter, vẫn không lọt.
        hits, records, excluded = _CASES["excluded_leak"]
        _patch_backends(monkeypatch, hits, records)

        results = _retriever().retrieve(
            "q", [0.1, 0.2, 0.3], owner_id="user-a", excluded_document_ids=excluded
        )

        assert results
        assert all(c.document_id != "d9" for c in results)
        assert {c.chunk_id for c in results} == {"a", "b", "g"}
