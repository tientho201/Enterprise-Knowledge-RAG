"""Data isolation ở tầng RAG retrieval — nối tiếp data isolation của documents.

`list_documents` đã owner-scoped (test_document_isolation.py); ở đây kiểm tra
`/chat` retrieval cũng bị cô lập: HybridRetriever chỉ truy hồi chunk của owner,
admin thấy tất cả. Test tập trung vào logic build filter (phần bảo mật cốt lõi)
— không cần Qdrant/Neo4j sống.
"""

from app.rag.retriever import HybridRetriever


class TestQdrantFilterIsolation:
    def test_owner_only_filter(self):
        f = HybridRetriever._build_qdrant_filter(document_ids=None, owner_id="user-a")
        assert f == {"must": [{"key": "owner_id", "match": {"value": "user-a"}}]}

    def test_owner_and_document_ids_combined(self):
        f = HybridRetriever._build_qdrant_filter(document_ids=["d1", "d2"], owner_id="user-a")
        assert f == {
            "must": [
                {"key": "document_id", "match": {"any": ["d1", "d2"]}},
                {"key": "owner_id", "match": {"value": "user-a"}},
            ]
        }

    def test_admin_no_owner_filter(self):
        # owner_id=None (admin) → không thêm điều kiện owner_id
        f = HybridRetriever._build_qdrant_filter(document_ids=None, owner_id=None)
        assert f is None

    def test_admin_with_document_ids_only(self):
        f = HybridRetriever._build_qdrant_filter(document_ids=["d1"], owner_id=None)
        assert f == {"must": [{"key": "document_id", "match": {"any": ["d1"]}}]}

    def test_owner_condition_always_present_for_non_admin(self):
        # Bảo vệ chống regression: mọi non-admin filter PHẢI kẹp owner_id.
        f = HybridRetriever._build_qdrant_filter(document_ids=["d1"], owner_id="user-a")
        assert f is not None
        keys = {cond["key"] for cond in f["must"]}
        assert "owner_id" in keys


class TestDenseSearchAppliesOwnerFilter:
    """Verify _dense_search thực sự gắn owner filter vào payload gửi Qdrant."""

    def test_dense_search_payload_includes_owner_filter(self, monkeypatch):
        captured: dict = {}

        class _FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"result": []}

        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json, headers):  # noqa: A002 - match httpx signature
                captured["payload"] = json
                return _FakeResponse()

        import httpx

        monkeypatch.setattr(httpx, "Client", _FakeClient)

        retriever = HybridRetriever()
        retriever._dense_search([0.1, 0.2, 0.3], document_ids=None, owner_id="user-a")

        assert captured["payload"]["filter"] == {
            "must": [{"key": "owner_id", "match": {"value": "user-a"}}]
        }

    def test_dense_search_admin_no_filter_key(self, monkeypatch):
        captured: dict = {}

        class _FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"result": []}

        class _FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json, headers):  # noqa: A002
                captured["payload"] = json
                return _FakeResponse()

        import httpx

        monkeypatch.setattr(httpx, "Client", _FakeClient)

        retriever = HybridRetriever()
        retriever._dense_search([0.1, 0.2, 0.3], document_ids=None, owner_id=None)

        # admin → không có key "filter" trong payload
        assert "filter" not in captured["payload"]


# ── Loại trừ tài liệu (excluded_document_ids) ────────────────────────────────


def _patch_httpx(monkeypatch, captured: dict, hits: list[dict] | None = None):
    """Thay httpx.Client bằng bản giả: ghi lại payload gửi Qdrant, trả `hits`."""

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"result": hits or []}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):  # noqa: A002 - match httpx signature
            captured["payload"] = json
            return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)


def _patch_neo4j(monkeypatch, captured: dict, records: list[dict] | None = None):
    """Thay Neo4j driver bằng bản giả: ghi lại câu Cypher + tham số, trả `records`."""

    class _FakeResult:
        @staticmethod
        def data():
            return records or []

    class _FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def run(self, query, **params):
            captured["query"] = query
            captured["params"] = params
            return _FakeResult()

    class _FakeDriver:
        @staticmethod
        def session():
            return _FakeSession()

    import app.rag.graph_client as graph_client

    monkeypatch.setattr(graph_client, "get_neo4j_driver", lambda: _FakeDriver())


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


def _record(chunk_id: str, document_id: str, connections: int = 1) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": f"{document_id}.pdf",
        "content": f"content of {chunk_id}",
        "chunk_index": 1,
        "connections": connections,
    }


_EXCLUDE_D9 = {"key": "document_id", "match": {"any": ["d9"]}}
_OWNER_A = {"key": "owner_id", "match": {"value": "user-a"}}
_EXCLUDED_CLAUSE = "AND NOT related.document_id IN $excluded_document_ids"
_OWNER_CLAUSE = "AND related.owner_id = $owner_id"


class TestQdrantFilterExclusion:
    def test_excluded_adds_must_not_and_keeps_owner(self):
        f = HybridRetriever._build_qdrant_filter(None, "user-a", excluded_document_ids=["d9"])
        assert f == {"must": [_OWNER_A], "must_not": [_EXCLUDE_D9]}

    def test_excluded_combined_with_document_ids_and_owner(self):
        f = HybridRetriever._build_qdrant_filter(
            ["d1", "d9"], "user-a", excluded_document_ids=["d9"]
        )
        # doc vừa được chọn vừa bị loại → must_not vẫn có mặt (loại trừ thắng),
        # và owner_id không bị rơi.
        assert f == {
            "must": [{"key": "document_id", "match": {"any": ["d1", "d9"]}}, _OWNER_A],
            "must_not": [_EXCLUDE_D9],
        }

    def test_admin_with_excluded_only_must_not(self):
        # admin (owner_id=None) vẫn phải loại doc bị loại trừ, và không tự dưng
        # sinh điều kiện owner_id.
        f = HybridRetriever._build_qdrant_filter(None, None, excluded_document_ids=["d9"])
        assert f == {"must_not": [_EXCLUDE_D9]}

    def test_empty_or_none_excluded_is_identical_to_before(self):
        cases: list[tuple[list[str] | None, str | None]] = [
            (None, "user-a"),
            (["d1", "d2"], "user-a"),
            (None, None),
            (["d1"], None),
        ]
        for document_ids, owner_id in cases:
            baseline = HybridRetriever._build_qdrant_filter(document_ids, owner_id)
            for excluded in (None, []):
                f = HybridRetriever._build_qdrant_filter(
                    document_ids, owner_id, excluded_document_ids=excluded
                )
                assert f == baseline
                assert f is None or "must_not" not in f

    def test_exclusion_never_removes_owner_condition(self):
        # Bảo vệ chống regression: thêm loại trừ không được nới lỏng owner filter.
        for document_ids in (None, ["d1"]):
            f = HybridRetriever._build_qdrant_filter(
                document_ids, "user-a", excluded_document_ids=["d9", "d8"]
            )
            assert f is not None
            assert _OWNER_A in f["must"]
            # owner_id không bao giờ nằm trong must_not / should
            assert all(cond["key"] == "document_id" for cond in f["must_not"])
            assert "should" not in f

    def test_excluded_list_is_copied_not_aliased(self):
        excluded = ["d9"]
        f = HybridRetriever._build_qdrant_filter(None, "user-a", excluded_document_ids=excluded)
        assert f is not None
        excluded.append("d10")
        assert f["must_not"] == [_EXCLUDE_D9]


class TestDenseSearchAppliesExclusion:
    def test_dense_search_payload_includes_must_not_and_owner(self, monkeypatch):
        captured: dict = {}
        _patch_httpx(monkeypatch, captured)

        HybridRetriever()._dense_search(
            [0.1, 0.2, 0.3], document_ids=None, owner_id="user-a", excluded_document_ids=["d9"]
        )

        assert captured["payload"]["filter"] == {"must": [_OWNER_A], "must_not": [_EXCLUDE_D9]}

    def test_dense_search_admin_payload_includes_must_not(self, monkeypatch):
        captured: dict = {}
        _patch_httpx(monkeypatch, captured)

        HybridRetriever()._dense_search(
            [0.1, 0.2, 0.3], document_ids=None, owner_id=None, excluded_document_ids=["d9"]
        )

        assert captured["payload"]["filter"] == {"must_not": [_EXCLUDE_D9]}

    def test_dense_search_empty_excluded_payload_unchanged(self, monkeypatch):
        for excluded in (None, []):
            captured: dict = {}
            _patch_httpx(monkeypatch, captured)

            HybridRetriever()._dense_search(
                [0.1, 0.2, 0.3],
                document_ids=None,
                owner_id="user-a",
                excluded_document_ids=excluded,
            )

            assert captured["payload"]["filter"] == {"must": [_OWNER_A]}

    def test_dense_search_positional_call_still_works(self, monkeypatch):
        # rag/graph_queries.py gọi _dense_search(embedding, document_ids, owner_id)
        # theo vị trí — chữ ký mới không được làm lệch các tham số này.
        captured: dict = {}
        _patch_httpx(monkeypatch, captured)

        HybridRetriever()._dense_search([0.1, 0.2, 0.3], ["d1"], "user-a", 0.5)

        assert captured["payload"]["score_threshold"] == 0.5
        assert captured["payload"]["filter"] == {
            "must": [{"key": "document_id", "match": {"any": ["d1"]}}, _OWNER_A]
        }


class TestGraphSearchAppliesExclusion:
    """Nhánh graph (Neo4j): NEXT_CHUNK/REFERENCES không được dẫn sang doc bị loại."""

    def test_graph_query_has_exclusion_and_owner_clauses(self, monkeypatch):
        captured: dict = {}
        _patch_neo4j(monkeypatch, captured)

        HybridRetriever()._graph_search(
            ["c1"], document_ids=None, owner_id="user-a", excluded_document_ids=["d9"]
        )

        assert _EXCLUDED_CLAUSE in captured["query"]
        assert _OWNER_CLAUSE in captured["query"]
        assert captured["params"]["excluded_document_ids"] == ["d9"]
        assert captured["params"]["owner_id"] == "user-a"

    def test_graph_query_admin_still_excludes(self, monkeypatch):
        captured: dict = {}
        _patch_neo4j(monkeypatch, captured)

        HybridRetriever()._graph_search(
            ["c1"], document_ids=None, owner_id=None, excluded_document_ids=["d9"]
        )

        assert _EXCLUDED_CLAUSE in captured["query"]
        assert _OWNER_CLAUSE not in captured["query"]
        assert captured["params"]["excluded_document_ids"] == ["d9"]

    def test_graph_query_without_excluded_has_no_exclusion_clause(self, monkeypatch):
        variants: list[dict] = [{}, {"excluded_document_ids": None}, {"excluded_document_ids": []}]
        for kwargs in variants:
            captured: dict = {}
            _patch_neo4j(monkeypatch, captured)

            HybridRetriever()._graph_search(
                ["c1"], document_ids=["d1"], owner_id="user-a", **kwargs
            )

            assert "excluded_document_ids" not in captured["query"]
            # owner + document scoping giữ nguyên như trước
            assert _OWNER_CLAUSE in captured["query"]
            assert "AND related.document_id IN $document_ids" in captured["query"]
            assert captured["params"]["owner_id"] == "user-a"
            assert captured["params"]["document_ids"] == ["d1"]


class TestRetrievePropagatesExclusion:
    """retrieve() phải đẩy danh sách loại trừ xuống CẢ hai nhánh."""

    def test_retrieve_passes_exclusion_to_dense_and_graph(self, monkeypatch):
        dense: dict = {}
        graph: dict = {}
        _patch_httpx(monkeypatch, dense, hits=[_hit("c1", "d1", 0.9)])
        _patch_neo4j(monkeypatch, graph, records=[_record("c2", "d1")])

        results = HybridRetriever().retrieve(
            "q", [0.1, 0.2, 0.3], owner_id="user-a", excluded_document_ids=["d9"]
        )

        assert dense["payload"]["filter"] == {"must": [_OWNER_A], "must_not": [_EXCLUDE_D9]}
        assert _EXCLUDED_CLAUSE in graph["query"]
        assert _OWNER_CLAUSE in graph["query"]
        assert graph["params"]["excluded_document_ids"] == ["d9"]
        assert graph["params"]["owner_id"] == "user-a"
        assert [c.chunk_id for c in results] == ["c1", "c2"]

    def test_retrieve_drops_excluded_chunks_even_if_backends_leak(self, monkeypatch):
        # Chốt chặn cuối: giả lập Qdrant và Neo4j đều "sót" chunk của doc d9.
        _patch_httpx(monkeypatch, {}, hits=[_hit("c1", "d1", 0.9), _hit("c9", "d9", 0.8)])
        _patch_neo4j(monkeypatch, {}, records=[_record("c2", "d1"), _record("c10", "d9", 5)])

        results = HybridRetriever().retrieve(
            "q", [0.1, 0.2, 0.3], owner_id="user-a", excluded_document_ids=["d9"]
        )

        assert {c.chunk_id for c in results} == {"c1", "c2"}
        assert all(c.document_id != "d9" for c in results)

    def test_retrieve_default_is_unchanged(self, monkeypatch):
        # Không truyền tham số mới → không must_not, không mệnh đề loại trừ,
        # không lọc bỏ chunk nào.
        dense: dict = {}
        graph: dict = {}
        _patch_httpx(monkeypatch, dense, hits=[_hit("c1", "d1", 0.9), _hit("c9", "d9", 0.8)])
        _patch_neo4j(monkeypatch, graph, records=[_record("c10", "d9")])

        results = HybridRetriever().retrieve("q", [0.1, 0.2, 0.3], owner_id="user-a")

        assert dense["payload"]["filter"] == {"must": [_OWNER_A]}
        assert "excluded_document_ids" not in graph["query"]
        assert _OWNER_CLAUSE in graph["query"]
        assert {c.chunk_id for c in results} == {"c1", "c9", "c10"}
