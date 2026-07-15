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
