"""search_mode="vector" phải chạy dense-only và không dùng chung Response Cache — T22.

Ba lớp kiểm:

1. `retriever_node` với HybridRetriever GIẢ (ghi lại lời gọi): "vector" không gọi
   `_graph_search`, `merge` lẫn `retrieve`; merged_results = kết quả dense theo điểm
   giảm dần. Các chế độ khác (sau T24): 1 `_graph_search` + 1 `merge`, không `retrieve`.
2. `retriever_node` với HybridRetriever THẬT, Qdrant (httpx) và Neo4j driver giả: đếm
   số lần lấy Neo4j driver để bắt cả đường GIÁN TIẾP (`retrieve()` tự gọi
   `_graph_search`), và kiểm payload gửi Qdrant vẫn mang đủ bộ lọc bảo mật.
3. `ChatService`: cache chỉ được đọc/ghi khi search_mode là None hoặc "hybrid".

Không cần Qdrant/Neo4j/OpenAI/Redis thật.
"""

import json
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import END, START, StateGraph

import app.rag.graph_client as graph_client
import app.rag.retriever as rag_retriever_module
from app.agents import retriever as retriever_module
from app.agents.graph import should_rewrite
from app.agents.retriever import retriever_node
from app.agents.state import AgentState
from app.models.document import DocumentType
from app.rag import response_cache
from app.rag.citation_retriever import CitationGraphResult
from app.rag.retriever import RetrievedChunk
from app.repositories.document_repo import DocumentRepository
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService

EMBEDDING = [0.1, 0.2, 0.3]
USER = "user-search-mode-vector"
ADMIN = "user-search-mode-admin"


def _chunk(chunk_id: str, document_id: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"{document_id}.pdf",
        content=f"content of {chunk_id}",
        score=score,
        chunk_index=0,
    )


def _state(**overrides) -> dict:
    state = {
        "query": "quy định nghỉ phép",
        "rewritten_query": None,
        "document_ids": ["d1", "d2"],
        "owner_id": "user-a",
        "similarity_threshold": 0.42,
        "search_mode": "vector",
    }
    state.update(overrides)
    return state


class _FakeEmbedder:
    def __init__(self):
        self.queries: list[str] = []

    def embed_query(self, query):
        self.queries.append(query)
        return EMBEDDING


# ── 1. Node với HybridRetriever giả ───────────────────────────────────────────


class _Recorder:
    def __init__(self):
        self.calls: dict[str, list[tuple[tuple, dict]]] = {
            "dense": [],
            "graph": [],
            "merge": [],
            "retrieve": [],
            "citation": [],
        }
        # Cố ý KHÔNG theo thứ tự điểm: node phải tự xếp giảm dần.
        self.dense_return = [
            _chunk("c-mid", "d1", 0.55),
            _chunk("c-top", "d2", 0.91),
            _chunk("c-low", "d1", 0.31),
        ]
        self.graph_return = {"g1": (_chunk("g1", "d1", 1.0), 1.0)}
        # Điểm hybrid khác hẳn điểm dense để lộ ra nếu nhánh vector lỡ dùng merge().
        self.merge_return = [_chunk("c-top", "d2", 0.7), _chunk("g1", "d1", 0.3)]
        # Dữ liệu lạ: lộ ngay nếu node (bất kỳ chế độ nào) còn lấy kết quả từ retrieve().
        self.retrieve_return = [_chunk("from-retrieve", "d1", 0.123)]


@pytest.fixture
def rec(monkeypatch) -> _Recorder:
    recorder = _Recorder()

    class _FakeRetriever:
        def _dense_search(self, *args, **kwargs):
            recorder.calls["dense"].append((args, kwargs))
            return list(recorder.dense_return)

        def _graph_search(self, *args, **kwargs):
            recorder.calls["graph"].append((args, kwargs))
            return dict(recorder.graph_return)

        # Chữ ký khớp HybridRetriever.merge: gọi lệch (thiếu/thừa tham số) → TypeError.
        def merge(self, dense_results, graph_results, *, excluded_document_ids=None):
            recorder.calls["merge"].append(
                ((dense_results, graph_results), {"excluded_document_ids": excluded_document_ids})
            )
            return list(recorder.merge_return)

        def retrieve(self, *args, **kwargs):
            recorder.calls["retrieve"].append((args, kwargs))
            return list(recorder.retrieve_return)

    def _fake_citation(*args, **kwargs):
        recorder.calls["citation"].append((args, kwargs))
        return CitationGraphResult()

    monkeypatch.setattr(retriever_module, "get_embedder", lambda: _FakeEmbedder())
    monkeypatch.setattr(retriever_module, "HybridRetriever", _FakeRetriever)
    monkeypatch.setattr(retriever_module, "graph_augmented_search", _fake_citation)
    return recorder


class TestVectorModeNode:
    async def test_vector_does_not_call_graph_search_or_retrieve(self, rec):
        await retriever_node(_state())

        assert len(rec.calls["dense"]) == 1
        assert rec.calls["graph"] == []
        assert rec.calls["merge"] == []
        assert rec.calls["retrieve"] == []  # retrieve() tự gọi _graph_search bên trong
        assert rec.calls["citation"] == []

    async def test_vector_merged_is_dense_sorted_by_score_desc(self, rec):
        result = await retriever_node(_state())

        assert result["merged_results"] == sorted(
            rec.dense_return, key=lambda c: c.score, reverse=True
        )
        assert [c.chunk_id for c in result["merged_results"]] == ["c-top", "c-mid", "c-low"]
        # Điểm cosine thô, không chuẩn hoá / nhân trọng số 0.7 như hybrid.
        assert [c.score for c in result["merged_results"]] == [0.91, 0.55, 0.31]
        assert result["graph_results"] == []
        assert result["dense_results"] == rec.dense_return

    async def test_vector_dense_call_keeps_every_security_argument(self, rec):
        await retriever_node(_state(excluded_document_ids=["d9"]))

        ((args, kwargs),) = rec.calls["dense"]
        assert args == (EMBEDDING,)
        assert kwargs == {
            "document_ids": ["d1", "d2"],
            "owner_id": "user-a",
            "score_threshold": 0.42,
            "excluded_document_ids": ["d9"],
        }

    async def test_vector_admin_still_passes_exclusion(self, rec):
        await retriever_node(_state(owner_id=None, excluded_document_ids=["d9"]))

        ((_, kwargs),) = rec.calls["dense"]
        assert kwargs["owner_id"] is None
        assert kwargs["excluded_document_ids"] == ["d9"]

    async def test_vector_backstop_drops_leaked_inactive_chunk(self, rec):
        """Filter Qdrant sót (payload lệch) → chunk của tài liệu tắt vẫn không vào state."""
        rec.dense_return = [_chunk("c9", "d9", 0.99), _chunk("c1", "d1", 0.5)]

        result = await retriever_node(_state(excluded_document_ids=["d9"]))

        assert [c.chunk_id for c in result["dense_results"]] == ["c1"]
        assert [c.chunk_id for c in result["merged_results"]] == ["c1"]
        assert result["graph_results"] == []

    async def test_vector_without_exclusion_key_keeps_all_dense(self, rec):
        state = _state()
        assert "excluded_document_ids" not in state

        result = await retriever_node(state)

        assert rec.calls["dense"][0][1]["excluded_document_ids"] is None
        assert len(result["merged_results"]) == 3

    async def test_vector_empty_dense_gives_empty_merged(self, rec):
        rec.dense_return = []

        result = await retriever_node(_state())

        assert result["merged_results"] == []
        assert result["graph_results"] == []
        assert rec.calls["graph"] == []
        assert rec.calls["merge"] == []
        assert rec.calls["retrieve"] == []

    async def test_vector_merged_does_not_alias_dense_objects(self, rec):
        result = await retriever_node(_state())

        dense_ids = {id(c) for c in result["dense_results"]}
        assert all(id(c) not in dense_ids for c in result["merged_results"])

    async def test_vector_citation_fields_stay_empty_and_state_passes_through(self, rec):
        result = await retriever_node(_state(excluded_document_ids=["d9"]))

        assert result["citation_graph_path"] == []
        assert result["citation_graph_nodes"] == []
        assert result["suggested_documents"] == []
        assert result["search_mode"] == "vector"
        assert result["owner_id"] == "user-a"
        assert result["excluded_document_ids"] == ["d9"]

    async def test_vector_retry_with_rewritten_query_stays_dense_only(self, rec, monkeypatch):
        embedder = _FakeEmbedder()
        monkeypatch.setattr(retriever_module, "get_embedder", lambda: embedder)

        await retriever_node(_state(rewritten_query="nghỉ phép năm", retry_count=1))

        assert embedder.queries == ["nghỉ phép năm"]
        assert len(rec.calls["dense"]) == 1
        assert rec.calls["graph"] == []
        assert rec.calls["merge"] == []
        assert rec.calls["retrieve"] == []


class TestOtherModesStayHybrid:
    @pytest.mark.parametrize("mode", [None, "hybrid"])
    async def test_default_and_hybrid_call_graph_search(self, rec, mode):
        result = await retriever_node(_state(search_mode=mode))

        assert len(rec.calls["graph"]) == 1
        assert len(rec.calls["merge"]) == 1
        assert rec.calls["retrieve"] == []
        ((args, kwargs),) = rec.calls["merge"]
        assert args == (rec.dense_return, rec.graph_return)
        assert kwargs == {"excluded_document_ids": None}  # state không có danh sách loại trừ
        assert result["merged_results"] == rec.merge_return
        assert [c.chunk_id for c in result["graph_results"]] == ["g1"]

    async def test_missing_search_mode_key_is_hybrid(self, rec):
        state = _state()
        del state["search_mode"]

        await retriever_node(state)

        assert len(rec.calls["graph"]) == 1
        assert len(rec.calls["merge"]) == 1
        assert rec.calls["retrieve"] == []
        assert rec.calls["merge"][0][1] == {"excluded_document_ids": None}

    @pytest.mark.parametrize("mode", [None, "hybrid", "keyword", "advanced"])
    async def test_hybrid_merge_receives_exclusion_list(self, rec, mode):
        """Sau T24 node gọi thẳng `merge()`: danh sách loại trừ PHẢI tới được nó (mặc
        định None = không loại gì, và `_drop_excluded` của node che mất lỗi ở đầu ra)."""
        await retriever_node(_state(search_mode=mode, excluded_document_ids=["d9", "d8"]))

        ((args, kwargs),) = rec.calls["merge"]
        assert args == (rec.dense_return, rec.graph_return)
        assert kwargs == {"excluded_document_ids": ["d9", "d8"]}
        assert rec.calls["retrieve"] == []

    @pytest.mark.parametrize("mode", ["keyword", "VECTOR", "Vector", " vector", "", "dense", "xyz"])
    async def test_keyword_and_unknown_values_keep_hybrid_behaviour(self, rec, mode):
        """D6: "keyword" chưa có hành vi riêng. Chỉ đúng chuỗi "vector" là dense-only;
        mọi giá trị khác (kể cả khác hoa/thường) đi đường hybrid như trước."""
        result = await retriever_node(_state(search_mode=mode))

        assert len(rec.calls["graph"]) == 1
        assert len(rec.calls["merge"]) == 1
        assert rec.calls["retrieve"] == []
        assert rec.calls["merge"][0][1] == {"excluded_document_ids": None}
        assert rec.calls["citation"] == []
        assert result["merged_results"] == rec.merge_return

    async def test_advanced_still_runs_hybrid_plus_citation_graph(self, rec):
        await retriever_node(_state(search_mode="advanced", excluded_document_ids=["d9"]))

        assert len(rec.calls["graph"]) == 1
        assert len(rec.calls["merge"]) == 1
        assert rec.calls["retrieve"] == []
        assert rec.calls["merge"][0][1] == {"excluded_document_ids": ["d9"]}
        ((args, kwargs),) = rec.calls["citation"]
        assert args[1:] == (["d1", "d2"], "user-a")
        assert kwargs == {"excluded_document_ids": ["d9"]}


# ── 2. Node với HybridRetriever thật: không chạm Neo4j ở BẤT KỲ đường nào ─────


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


class _Infra:
    def __init__(self):
        self.qdrant_payloads: list[dict] = []
        self.neo4j_driver_requests = 0
        self.hits: list[dict] = [
            _hit("c-mid", "d1", 0.55),
            _hit("c-top", "d2", 0.91),
            _hit("c-low", "d1", 0.31),
        ]


@pytest.fixture
def infra(monkeypatch) -> _Infra:
    """HybridRetriever THẬT; chỉ thay tầng mạng. Mọi lần xin Neo4j driver đều bị đếm
    rồi ném lỗi (như Neo4j chết) — `_graph_search` nuốt lỗi nên phải dựa vào bộ đếm."""
    state = _Infra()

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"result": list(state.hits)}

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json, headers):  # noqa: A002 - match httpx signature
            state.qdrant_payloads.append(json)
            return _FakeResponse()

    def _neo4j_down(*a, **k):
        state.neo4j_driver_requests += 1
        raise ConnectionError("neo4j down (test)")

    class _NoGraphDatabase:
        driver = staticmethod(_neo4j_down)

    import httpx

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(rag_retriever_module, "get_qdrant_client", lambda: None)
    monkeypatch.setattr(graph_client, "get_neo4j_driver", _neo4j_down)
    monkeypatch.setattr(graph_client, "GraphDatabase", _NoGraphDatabase)
    monkeypatch.setattr(retriever_module, "get_embedder", lambda: _FakeEmbedder())
    return state


class TestVectorModeNeverTouchesNeo4j:
    async def test_vector_makes_zero_neo4j_driver_requests(self, infra):
        result = await retriever_node(_state())

        assert infra.neo4j_driver_requests == 0
        assert len(infra.qdrant_payloads) == 1  # đúng một lượt dense, không lặp
        assert [c.chunk_id for c in result["merged_results"]] == ["c-top", "c-mid", "c-low"]
        assert [c.score for c in result["merged_results"]] == [0.91, 0.55, 0.31]
        assert result["graph_results"] == []

    @pytest.mark.parametrize("mode", [None, "hybrid", "keyword"])
    async def test_control_hybrid_modes_do_reach_neo4j(self, infra, mode):
        """Đối chứng: bộ đếm bắt được lời gọi Neo4j của đường hybrid."""
        await retriever_node(_state(search_mode=mode))

        # Sau T24: đúng 1 lần `_graph_search` (node không còn gọi `retrieve()`, thứ từng
        # chạy lại cả dense lẫn graph → 2 lần mỗi loại).
        assert infra.neo4j_driver_requests == 1
        assert len(infra.qdrant_payloads) == 1

    async def test_control_advanced_reaches_neo4j_twice(self, infra):
        await retriever_node(_state(search_mode="advanced"))

        assert infra.neo4j_driver_requests == 2  # _graph_search + graph_augmented_search
        assert len(infra.qdrant_payloads) == 1

    async def test_vector_qdrant_payload_carries_owner_scope_and_exclusion(self, infra):
        await retriever_node(_state(excluded_document_ids=["d9", "d8"]))

        (payload,) = infra.qdrant_payloads
        assert payload["filter"] == {
            "must": [
                {"key": "document_id", "match": {"any": ["d1", "d2"]}},
                {"key": "owner_id", "match": {"value": "user-a"}},
            ],
            "must_not": [{"key": "document_id", "match": {"any": ["d9", "d8"]}}],
        }
        assert payload["score_threshold"] == 0.42
        assert infra.neo4j_driver_requests == 0

    async def test_vector_filter_identical_to_hybrid_dense_filter(self, infra):
        """Nhánh vector không được tạo đường tắt: filter Qdrant y hệt lượt dense của hybrid."""
        await retriever_node(_state(search_mode="hybrid", excluded_document_ids=["d9"]))
        hybrid_payload = infra.qdrant_payloads[0]
        infra.qdrant_payloads.clear()

        await retriever_node(_state(search_mode="vector", excluded_document_ids=["d9"]))

        assert infra.qdrant_payloads == [hybrid_payload]

    async def test_vector_admin_has_no_owner_filter_but_keeps_exclusion(self, infra):
        await retriever_node(_state(owner_id=None, document_ids=None, excluded_document_ids=["d9"]))

        (payload,) = infra.qdrant_payloads
        assert payload["filter"] == {"must_not": [{"key": "document_id", "match": {"any": ["d9"]}}]}

    async def test_inactive_document_never_appears_in_vector_mode(self, infra):
        """Tài liệu tắt d9 lọt filter Qdrant (giả lập payload lệch) với điểm cao nhất:
        không được xuất hiện ở bất kỳ danh sách kết quả nào của chế độ vector."""
        infra.hits = [_hit("c9", "d9", 0.99), _hit("c1", "d1", 0.6), _hit("c2", "d2", 0.7)]

        result = await retriever_node(_state(excluded_document_ids=["d9"]))

        for key in ("dense_results", "graph_results", "merged_results"):
            assert all(c.document_id != "d9" for c in result[key]), key
        assert [c.chunk_id for c in result["merged_results"]] == ["c2", "c1"]
        assert infra.neo4j_driver_requests == 0

    async def test_vector_stays_dense_only_across_rewriter_retry_loop(self, infra):
        """Chạy vòng retriever → grader → rewriter → retriever qua LangGraph thật
        (grader/rewriter giả, điều kiện `should_rewrite` thật): cả hai lượt truy hồi
        đều dense-only và vẫn mang đủ bộ lọc."""

        async def fake_grader(state):
            return {**state, "reranked_results": [], "confidence_score": 0.0}

        async def fake_rewriter(state):
            return {
                **state,
                "rewritten_query": "câu hỏi viết lại",
                "retry_count": state.get("retry_count", 0) + 1,
            }

        graph = StateGraph(AgentState)
        graph.add_node("retriever", retriever_node)
        graph.add_node("grader", fake_grader)
        graph.add_node("rewriter", fake_rewriter)
        graph.add_edge(START, "retriever")
        graph.add_edge("retriever", "grader")
        graph.add_conditional_edges(
            "grader", should_rewrite, {"rewrite": "rewriter", "generate": END}
        )
        graph.add_edge("rewriter", "retriever")

        final = await graph.compile().ainvoke(
            _state(excluded_document_ids=["d9"], retry_count=0, confidence_score=0.0)
        )

        assert final["retry_count"] == 2  # MAX_RETRIES → 3 lượt truy hồi
        assert len(infra.qdrant_payloads) == 3
        assert infra.neo4j_driver_requests == 0
        for payload in infra.qdrant_payloads:
            assert payload["filter"]["must_not"] == [
                {"key": "document_id", "match": {"any": ["d9"]}}
            ]
            assert {"key": "owner_id", "match": {"value": "user-a"}} in payload["filter"]["must"]
        assert final["search_mode"] == "vector"
        assert final["graph_results"] == []


# ── 3. ChatService: Response Cache theo search_mode ───────────────────────────


class FakeGraph:
    def __init__(self, result: dict):
        self.result = result
        self.states: list[dict] = []

    async def ainvoke(self, state):
        self.states.append(dict(state))
        return {**state, **self.result}


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        self.store[key] = value

    async def incr(self, key: str) -> int:
        current = int(self.store.get(key, "0")) + 1
        self.store[key] = str(current)
        return current


@pytest.fixture
def agent_graph(monkeypatch):
    graph = FakeGraph({"final_answer": "tra loi", "citations": [], "intent": "rag"})
    monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
    return graph


@pytest.fixture
def retrieval_graph(monkeypatch):
    graph = FakeGraph({"intent": "chitchat"})
    monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
    return graph


@pytest.fixture
def generator(monkeypatch):
    node = AsyncMock(return_value={"final_answer": "tra loi", "citations": []})
    monkeypatch.setattr("app.agents.generator.generator_node", node)
    return node


@pytest.fixture
def cache_spy(monkeypatch):
    get = AsyncMock(return_value=None)
    set_ = AsyncMock()
    monkeypatch.setattr(chat_service_module, "get_cached_answer", get)
    monkeypatch.setattr(chat_service_module, "set_cached_answer", set_)
    return get, set_


@pytest.fixture
def fake_redis(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(response_cache, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def stream_db(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "commit", AsyncMock())
    return db_session


async def _run_stream(service: ChatService, **kwargs) -> list[dict]:
    events = []
    async for raw in service.chat_stream(**kwargs):
        assert raw.startswith("data: ")
        events.append(json.loads(raw[len("data: ") :]))
    return events


async def _inactive_doc(db, owner_id: str) -> str:
    repo = DocumentRepository(db)
    doc = await repo.create(name="off.pdf", doc_type=DocumentType.pdf, owner_id=owner_id)
    await repo.set_active(doc.id, False)
    await db.flush()
    return doc.id


class TestChatCacheBySearchMode:
    async def test_vector_does_not_read_or_write_cache(self, db_session, agent_graph, cache_spy):
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=USER, message="hoi", search_mode="vector")

        get.assert_not_awaited()
        set_.assert_not_awaited()
        assert len(agent_graph.states) == 1

    @pytest.mark.parametrize("mode", [None, "hybrid"])
    async def test_default_and_hybrid_read_and_write_cache(
        self, db_session, agent_graph, cache_spy, mode
    ):
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=USER, message="hoi", search_mode=mode)

        get.assert_awaited_once()
        set_.assert_awaited_once()
        # Cache key không đổi so với trước T22 (không chứa search_mode).
        assert get.await_args.args == ("hoi", USER, None)
        assert set_.await_args.args[:3] == ("hoi", USER, None)

    async def test_search_mode_omitted_still_caches(self, db_session, agent_graph, cache_spy):
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=USER, message="hoi")

        get.assert_awaited_once()
        set_.assert_awaited_once()

    @pytest.mark.parametrize("mode", ["keyword", "advanced", "VECTOR", "Hybrid", ""])
    async def test_other_modes_do_not_use_cache(self, db_session, agent_graph, cache_spy, mode):
        """Chỉ None/"hybrid" được cache. "keyword" hiện truy hồi như hybrid nhưng KHÔNG
        cache (theo yêu cầu T22: an toàn khi sau này keyword có hành vi riêng)."""
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=USER, message="hoi", search_mode=mode)

        get.assert_not_awaited()
        set_.assert_not_awaited()
        assert agent_graph.states[0]["search_mode"] == mode

    @pytest.mark.parametrize(
        "extra",
        [
            {"search_tool": True},
            {"system_prompt": "x"},
            {"model": "m"},
            {"api_key": "k"},
            {"base_url": "http://x"},
        ],
    )
    async def test_existing_cache_exclusions_still_apply_in_hybrid(
        self, db_session, agent_graph, cache_spy, extra
    ):
        get, set_ = cache_spy

        await ChatService(db_session).chat(
            user_id=USER, message="hoi", search_mode="hybrid", **extra
        )

        get.assert_not_awaited()
        set_.assert_not_awaited()

    async def test_vector_state_carries_mode_owner_and_exclusion(
        self, db_session, agent_graph, cache_spy
    ):
        doc_id = await _inactive_doc(db_session, USER)

        await ChatService(db_session).chat(
            user_id=USER, message="hoi", search_mode="vector", document_ids=["d1"]
        )

        (state,) = agent_graph.states
        assert state["search_mode"] == "vector"
        assert state["owner_id"] == USER
        assert state["document_ids"] == ["d1"]
        assert state["excluded_document_ids"] == [doc_id]

    async def test_vector_admin_state_has_no_owner_but_keeps_exclusion(
        self, db_session, agent_graph, cache_spy
    ):
        doc_id = await _inactive_doc(db_session, USER)

        await ChatService(db_session).chat(
            user_id=ADMIN, message="hoi", search_mode="vector", is_admin=True
        )

        (state,) = agent_graph.states
        assert state["owner_id"] is None
        assert doc_id in state["excluded_document_ids"]

    async def test_vector_fails_closed_when_inactive_lookup_errors(
        self, db_session, agent_graph, cache_spy, monkeypatch
    ):
        async def boom(self, owner_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", boom)

        with pytest.raises(RuntimeError):
            await ChatService(db_session).chat(user_id=USER, message="hoi", search_mode="vector")

        assert agent_graph.states == []

    async def test_vector_and_hybrid_never_share_cached_answers(
        self, db_session, monkeypatch, fake_redis
    ):
        """Cache thật (FakeRedis): câu trả lời hybrid không được trả cho vector, và lượt
        vector không được ghi đè entry của hybrid."""
        graph = FakeGraph({"final_answer": "tra loi HYBRID", "citations": [], "intent": "rag"})
        monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
        service = ChatService(db_session)
        msg = "cau hoi dung chung"

        first = await service.chat(user_id=USER, message=msg, search_mode="hybrid")
        assert first.message.content == "tra loi HYBRID"
        assert len(graph.states) == 1

        graph.result = {"final_answer": "tra loi VECTOR", "citations": [], "intent": "rag"}
        vector = await service.chat(user_id=USER, message=msg, search_mode="vector")
        assert vector.message.content == "tra loi VECTOR"  # không lấy cache của hybrid
        assert len(graph.states) == 2

        graph.result = {"final_answer": "KHONG DUOC THAY", "citations": [], "intent": "rag"}
        for mode in ("hybrid", None):
            again = await service.chat(user_id=USER, message=msg, search_mode=mode)
            assert again.message.content == "tra loi HYBRID"  # entry hybrid còn nguyên
        assert len(graph.states) == 2  # hai lượt cuối là cache hit

    async def test_vector_first_does_not_seed_cache_for_hybrid(
        self, db_session, monkeypatch, fake_redis
    ):
        graph = FakeGraph({"final_answer": "tra loi VECTOR", "citations": [], "intent": "rag"})
        monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
        service = ChatService(db_session)
        msg = "cau hoi vector truoc"

        await service.chat(user_id=USER, message=msg, search_mode="vector")
        assert not any(k.startswith("response_cache:entry:") for k in fake_redis.store)

        graph.result = {"final_answer": "tra loi HYBRID", "citations": [], "intent": "rag"}
        hybrid = await service.chat(user_id=USER, message=msg, search_mode="hybrid")

        assert hybrid.message.content == "tra loi HYBRID"
        assert len(graph.states) == 2
        # Đối chứng: tiền tố key đúng — lượt hybrid CÓ ghi cache.
        assert any(k.startswith("response_cache:entry:") for k in fake_redis.store)


class TestChatStreamVector:
    """/chat/stream không dùng Response Cache; khoá lại để không ai thêm cache dùng chung
    key cho mọi search_mode, và kiểm state vẫn mang đủ chế độ + bộ lọc."""

    @pytest.mark.parametrize("mode", [None, "hybrid", "vector", "keyword"])
    async def test_stream_never_touches_response_cache(
        self, stream_db, retrieval_graph, generator, cache_spy, mode
    ):
        get, set_ = cache_spy

        events = await _run_stream(
            ChatService(stream_db), user_id=USER, message="hoi", search_mode=mode
        )

        assert events[-1]["type"] == "done"
        get.assert_not_awaited()
        set_.assert_not_awaited()

    async def test_stream_vector_state_carries_mode_owner_and_exclusion(
        self, stream_db, retrieval_graph, generator, cache_spy
    ):
        doc_id = await _inactive_doc(stream_db, USER)

        events = await _run_stream(
            ChatService(stream_db),
            user_id=USER,
            message="hoi",
            search_mode="vector",
            document_ids=["d1"],
        )

        assert events[-1]["type"] == "done"
        (state,) = retrieval_graph.states
        assert state["search_mode"] == "vector"
        assert state["owner_id"] == USER
        assert state["document_ids"] == ["d1"]
        assert state["excluded_document_ids"] == [doc_id]
        # State đưa tiếp cho generator_node vẫn là state đó.
        assert generator.await_args.args[0]["search_mode"] == "vector"
        assert generator.await_args.args[0]["excluded_document_ids"] == [doc_id]
