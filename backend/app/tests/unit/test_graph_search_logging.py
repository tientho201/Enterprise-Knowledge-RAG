"""`_graph_search` phải GHI LOG khi Neo4j lỗi, không được nuốt im lặng.

Hành vi degrade giữ nguyên (trả `{}` → pipeline rơi về dense-only), nhưng phải
có đúng một bản ghi WARNING kèm traceback để người vận hành biết nhánh graph
đang tắt. Bản ghi chỉ được chứa số đếm + owner_id — không nội dung chunk, không
câu hỏi (PII).

Không cần Qdrant/Neo4j sống: `_graph_search` import `get_neo4j_driver` từ
`app.rag.graph_client` NGAY TRONG thân hàm, nên monkeypatch thuộc tính trên
module `graph_client` là đủ.
"""

import logging

import pytest

from app.rag.retriever import HybridRetriever

_LOGGER_NAME = "app.rag.retriever"

_SECRET_CONTENT = "NOI-DUNG-MAT-luong-thang-13-cua-ong-A"
_SECRET_QUERY = "CAU-HOI-MAT-so-cmnd-012345678"


class _Neo4jDownError(Exception):
    pass


def _patch_driver_raises(monkeypatch, exc: Exception) -> None:
    """`get_neo4j_driver()` ném `exc` (vd Neo4j không kết nối được)."""

    def _boom():
        raise exc

    import app.rag.graph_client as graph_client

    monkeypatch.setattr(graph_client, "get_neo4j_driver", _boom)


def _patch_session_run(monkeypatch, *, exc: Exception | None = None, records=None) -> None:
    """Driver lấy được; `session.run` ném `exc` hoặc trả `records`."""

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
            if exc is not None:
                raise exc
            return _FakeResult()

    class _FakeDriver:
        @staticmethod
        def session():
            return _FakeSession()

    import app.rag.graph_client as graph_client

    monkeypatch.setattr(graph_client, "get_neo4j_driver", lambda: _FakeDriver())


def _patch_httpx(monkeypatch, hits: list[dict]) -> None:
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
            return _FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)


def _retriever_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER_NAME]


@pytest.fixture
def caplog_retriever(caplog):
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    return caplog


class TestGraphSearchLogsNeo4jFailure:
    def test_driver_failure_returns_empty_and_logs_one_warning(self, monkeypatch, caplog_retriever):
        exc = _Neo4jDownError("connection refused")
        _patch_driver_raises(monkeypatch, exc)

        result = HybridRetriever()._graph_search(["c1"])

        assert result == {}
        records = _retriever_records(caplog_retriever)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.WARNING
        # exc_info=True → traceback của đúng exception gốc đi kèm bản ghi
        assert record.exc_info is not None
        assert record.exc_info[0] is _Neo4jDownError
        assert record.exc_info[1] is exc

    def test_query_failure_also_logged(self, monkeypatch, caplog_retriever):
        # Driver tạo được nhưng câu Cypher lỗi (vd sai cú pháp, timeout).
        exc = _Neo4jDownError("query timed out")
        _patch_session_run(monkeypatch, exc=exc)

        result = HybridRetriever()._graph_search(["c1", "c2"], owner_id="user-a")

        assert result == {}
        records = _retriever_records(caplog_retriever)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].exc_info is not None
        assert records[0].exc_info[1] is exc

    def test_log_carries_seed_count_and_owner_id(self, monkeypatch, caplog_retriever):
        _patch_driver_raises(monkeypatch, _Neo4jDownError("down"))

        HybridRetriever()._graph_search(
            ["c1", "c2", "c3"], owner_id="user-a", excluded_document_ids=["d9", "d8"]
        )

        (record,) = _retriever_records(caplog_retriever)
        message = record.getMessage()
        assert "seed_count=3" in message
        assert "owner_id=user-a" in message
        assert "excluded_count=2" in message

    def test_log_for_admin_has_owner_none(self, monkeypatch, caplog_retriever):
        _patch_driver_raises(monkeypatch, _Neo4jDownError("down"))

        HybridRetriever()._graph_search(["c1"], owner_id=None)

        (record,) = _retriever_records(caplog_retriever)
        message = record.getMessage()
        assert "seed_count=1" in message
        assert "owner_id=None" in message
        assert "excluded_count=0" in message


class TestGraphSearchLogHasNoPii:
    def test_log_has_no_chunk_content_or_query(self, monkeypatch, caplog_retriever):
        # Đi qua retrieve() để câu hỏi và nội dung chunk THỰC SỰ có mặt trong
        # luồng xử lý lúc Neo4j lỗi.
        _patch_httpx(
            monkeypatch,
            hits=[
                {
                    "id": "chunk-id-abc",
                    "score": 0.9,
                    "payload": {
                        "document_id": "d1",
                        "document_name": "d1.pdf",
                        "content": _SECRET_CONTENT,
                        "chunk_index": 0,
                    },
                }
            ],
        )
        _patch_driver_raises(monkeypatch, _Neo4jDownError("down"))

        results = HybridRetriever().retrieve(_SECRET_QUERY, [0.1, 0.2, 0.3], owner_id="user-a")

        # degrade về dense-only: chunk dense vẫn được trả về
        assert [c.chunk_id for c in results] == ["chunk-id-abc"]
        assert results[0].content == _SECRET_CONTENT

        (record,) = _retriever_records(caplog_retriever)
        assert record.levelno == logging.WARNING
        # Kiểm cả message đã format, tham số thô, lẫn toàn bộ text (gồm traceback).
        haystacks = [record.getMessage(), repr(record.args), caplog_retriever.text]
        for haystack in haystacks:
            assert _SECRET_CONTENT not in haystack
            assert _SECRET_QUERY not in haystack
            # seed_ids cũng không được ghi — chỉ ghi số lượng
            assert "chunk-id-abc" not in haystack
        assert "seed_count=1" in record.getMessage()

    def test_log_args_are_only_counts_and_owner(self, monkeypatch, caplog_retriever):
        # Chặn regression kiểu "tiện tay log luôn seed_ids/document_ids".
        _patch_driver_raises(monkeypatch, _Neo4jDownError("down"))

        HybridRetriever()._graph_search(
            ["c1", "c2"], document_ids=["d1"], owner_id="user-a", excluded_document_ids=["d9"]
        )

        (record,) = _retriever_records(caplog_retriever)
        assert record.args == (2, "user-a", 1)


class TestGraphSearchNoLogWhenHealthy:
    def test_empty_seeds_no_log_and_no_driver_call(self, monkeypatch, caplog_retriever):
        _patch_driver_raises(monkeypatch, AssertionError("driver must not be requested"))

        assert HybridRetriever()._graph_search([]) == {}
        assert _retriever_records(caplog_retriever) == []

    def test_success_with_no_records_no_log(self, monkeypatch, caplog_retriever):
        _patch_session_run(monkeypatch, records=[])

        assert HybridRetriever()._graph_search(["c1"]) == {}
        assert _retriever_records(caplog_retriever) == []

    def test_success_with_records_no_log(self, monkeypatch, caplog_retriever):
        _patch_session_run(
            monkeypatch,
            records=[
                {
                    "chunk_id": "c2",
                    "document_id": "d1",
                    "document_name": "d1.pdf",
                    "content": _SECRET_CONTENT,
                    "chunk_index": 1,
                    "connections": 2,
                }
            ],
        )

        result = HybridRetriever()._graph_search(["c1"], owner_id="user-a")

        assert set(result) == {"c2"}
        assert result["c2"][1] == 1.0
        assert _retriever_records(caplog_retriever) == []
