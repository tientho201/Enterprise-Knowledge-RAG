"""ChatService phải loại tài liệu đang tắt (`is_active=False`) khỏi RAG — T10.

Kiểm ở tầng service với graph giả ghi lại state đầu vào (không gọi Qdrant/Neo4j/LLM):
`state["excluded_document_ids"]` phải chứa đúng ID tài liệu tắt trong phạm vi
`owner_id` mà luồng chat dùng cho retrieval, ở CẢ `/chat` (chat) và `/chat/stream`
(chat_stream), cho user thường lẫn admin; lỗi DB khi lấy danh sách thì retrieval
KHÔNG được chạy (fail-closed); đường trả từ Response Cache không được trả câu trả
lời cache từ lúc tài liệu còn bật.

DB: SQLite in-memory (fixture db_session). Redis: FakeRedis tối giản.
"""

import json
from unittest.mock import AsyncMock

import pytest
from langgraph.graph import END, START, StateGraph

from app.agents.state import AgentState
from app.models.document import DocumentType
from app.rag import response_cache
from app.repositories.document_repo import DocumentRepository
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService, _cache_document_scope

USER_A = "user-chat-inactive-aaaa"
USER_B = "user-chat-inactive-bbbb"
USER_CLEAN = "user-chat-inactive-clean"  # không có tài liệu tắt nào
ADMIN = "user-chat-inactive-admin"


class FakeGraph:
    """Thay graph LangGraph: ghi lại state nhận được, trả state kết quả cố định."""

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


async def _seed(db) -> dict:
    """USER_A: 1 bật + 1 tắt + 1 tắt-đã-xoá; USER_B: 1 bật + 1 tắt; USER_CLEAN: 1 bật."""
    repo = DocumentRepository(db)

    async def _doc(name: str, owner_id: str, *, active: bool):
        doc = await repo.create(name=name, doc_type=DocumentType.pdf, owner_id=owner_id)
        if not active:
            await repo.set_active(doc.id, False)
        return doc

    docs = {
        "a_on": await _doc("a-on.pdf", USER_A, active=True),
        "a_off": await _doc("a-off.pdf", USER_A, active=False),
        "a_off_deleted": await _doc("a-off-deleted.pdf", USER_A, active=False),
        "b_on": await _doc("b-on.pdf", USER_B, active=True),
        "b_off": await _doc("b-off.pdf", USER_B, active=False),
        "clean_on": await _doc("clean-on.pdf", USER_CLEAN, active=True),
    }
    assert await repo.soft_delete(docs["a_off_deleted"].id) is True
    await db.flush()
    return docs


@pytest.fixture
def agent_graph(monkeypatch):
    graph = FakeGraph({"final_answer": "tra loi", "citations": [], "intent": "rag"})
    monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
    return graph


@pytest.fixture
def retrieval_graph(monkeypatch):
    # intent chitchat → chat_stream đi nhánh generator_node (không cần LLM stream giả)
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
    """Cache luôn miss, ghi lại tham số — mặc định cho test không quan tâm tới cache."""
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
    """chat_stream tự commit; chặn lại để dữ liệu test không rò sang test khác
    (engine SQLite dùng chung cả session pytest)."""
    monkeypatch.setattr(db_session, "commit", AsyncMock())
    return db_session


async def _run_stream(service: ChatService, **kwargs) -> list[dict]:
    events = []
    async for raw in service.chat_stream(**kwargs):
        assert raw.startswith("data: ")
        events.append(json.loads(raw[len("data: ") :]))
    return events


# ── /chat (không stream) ──────────────────────────────────────────────────────


class TestChatNonStream:
    async def test_user_state_excludes_exactly_own_inactive_doc(
        self, db_session, agent_graph, cache_spy
    ):
        docs = await _seed(db_session)

        await ChatService(db_session).chat(user_id=USER_A, message="hoi gi do")

        (state,) = agent_graph.states
        assert state["excluded_document_ids"] == [docs["a_off"].id]
        assert state["owner_id"] == USER_A

    async def test_excluded_ids_are_exact_document_id_strings(
        self, db_session, agent_graph, cache_spy
    ):
        """So khớp ở Qdrant/Neo4j là chuỗi chính xác: ID trong state phải đúng là
        `Document.id` (str 36 ký tự) như ingestion ghi vào payload, không phải UUID object."""
        docs = await _seed(db_session)

        await ChatService(db_session).chat(user_id=USER_A, message="hoi gi do")

        (excluded_id,) = agent_graph.states[0]["excluded_document_ids"]
        assert type(excluded_id) is str
        assert excluded_id == docs["a_off"].id
        assert len(excluded_id) == 36

    async def test_user_does_not_get_other_users_inactive_doc(
        self, db_session, agent_graph, cache_spy
    ):
        docs = await _seed(db_session)

        await ChatService(db_session).chat(user_id=USER_A, message="hoi gi do")

        excluded = agent_graph.states[0]["excluded_document_ids"]
        assert docs["b_off"].id not in excluded
        assert docs["a_on"].id not in excluded
        assert docs["a_off_deleted"].id not in excluded

    async def test_admin_state_excludes_inactive_docs_of_all_users(
        self, db_session, agent_graph, cache_spy
    ):
        docs = await _seed(db_session)

        await ChatService(db_session).chat(user_id=ADMIN, message="hoi gi do", is_admin=True)

        (state,) = agent_graph.states
        assert state["owner_id"] is None
        # Tập con: engine SQLite dùng chung nên có thể còn doc tắt của test khác.
        assert {docs["a_off"].id, docs["b_off"].id} <= set(state["excluded_document_ids"])
        assert docs["a_on"].id not in state["excluded_document_ids"]
        assert docs["b_on"].id not in state["excluded_document_ids"]

    async def test_user_without_inactive_docs_gets_empty_list(
        self, db_session, agent_graph, cache_spy
    ):
        await _seed(db_session)

        await ChatService(db_session).chat(user_id=USER_CLEAN, message="hoi gi do")

        (state,) = agent_graph.states
        assert state["excluded_document_ids"] == []
        assert state["owner_id"] == USER_CLEAN

    @pytest.mark.parametrize("client_document_ids", [None, []])
    async def test_empty_document_ids_keeps_whole_library_semantics(
        self, db_session, agent_graph, cache_spy, client_document_ids
    ):
        """documentIds rỗng/None từ client: giữ nguyên (= cả thư viện), chỉ thêm loại trừ."""
        docs = await _seed(db_session)

        await ChatService(db_session).chat(
            user_id=USER_A, message="hoi gi do", document_ids=client_document_ids
        )

        (state,) = agent_graph.states
        assert state["document_ids"] == client_document_ids
        assert state["excluded_document_ids"] == [docs["a_off"].id]

    async def test_explicit_document_ids_pass_through_and_exclusion_still_applies(
        self, db_session, agent_graph, cache_spy
    ):
        """Client gửi thẳng ID tài liệu tắt: document_ids không bị sửa, nhưng ID đó vẫn
        nằm trong danh sách loại trừ (tầng retrieval ưu tiên loại trừ)."""
        docs = await _seed(db_session)
        requested = [docs["a_on"].id, docs["a_off"].id]

        await ChatService(db_session).chat(
            user_id=USER_A, message="hoi gi do", document_ids=requested
        )

        (state,) = agent_graph.states
        assert state["document_ids"] == requested
        assert state["excluded_document_ids"] == [docs["a_off"].id]

    async def test_repo_called_with_retrieval_owner_scope(
        self, db_session, agent_graph, cache_spy, monkeypatch
    ):
        """owner_id truyền cho repo phải ĐÚNG owner_id của retrieval (admin → None)."""
        seen: list = []

        async def fake_list(self, owner_id):
            seen.append(owner_id)
            return []

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", fake_list)
        service = ChatService(db_session)

        await service.chat(user_id=USER_A, message="hoi gi do")
        await service.chat(user_id=ADMIN, message="hoi gi do", is_admin=True)

        assert seen == [USER_A, None]
        assert [s["owner_id"] for s in agent_graph.states] == [USER_A, None]

    async def test_db_error_fails_closed_no_retrieval(
        self, db_session, agent_graph, cache_spy, monkeypatch
    ):
        async def boom(self, owner_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", boom)

        with pytest.raises(RuntimeError, match="db down"):
            await ChatService(db_session).chat(user_id=USER_A, message="hoi gi do")

        get, set_ = cache_spy
        assert agent_graph.states == []  # graph (retrieval) không được chạy
        get.assert_not_awaited()  # cũng không được trả từ cache
        set_.assert_not_awaited()


# ── /chat/stream ──────────────────────────────────────────────────────────────


class TestChatStream:
    async def test_user_state_excludes_exactly_own_inactive_doc(
        self, stream_db, retrieval_graph, generator
    ):
        docs = await _seed(stream_db)

        events = await _run_stream(ChatService(stream_db), user_id=USER_A, message="hoi gi do")

        assert [e["type"] for e in events] == ["meta", "delta", "done"]
        (state,) = retrieval_graph.states
        assert state["excluded_document_ids"] == [docs["a_off"].id]
        assert type(state["excluded_document_ids"][0]) is str
        assert state["owner_id"] == USER_A
        assert docs["b_off"].id not in state["excluded_document_ids"]

    async def test_state_handed_to_generator_keeps_exclusion(
        self, stream_db, retrieval_graph, generator
    ):
        """State phụ của luồng stream (đưa vào generator_node) vẫn mang danh sách loại trừ."""
        docs = await _seed(stream_db)

        await _run_stream(ChatService(stream_db), user_id=USER_A, message="hoi gi do")

        (gen_state,) = generator.await_args.args
        assert gen_state["excluded_document_ids"] == [docs["a_off"].id]
        assert gen_state["owner_id"] == USER_A

    async def test_admin_state_excludes_inactive_docs_of_all_users(
        self, stream_db, retrieval_graph, generator
    ):
        docs = await _seed(stream_db)

        await _run_stream(ChatService(stream_db), user_id=ADMIN, message="hoi gi do", is_admin=True)

        (state,) = retrieval_graph.states
        assert state["owner_id"] is None
        assert {docs["a_off"].id, docs["b_off"].id} <= set(state["excluded_document_ids"])
        assert docs["a_on"].id not in state["excluded_document_ids"]

    async def test_user_without_inactive_docs_gets_empty_list(
        self, stream_db, retrieval_graph, generator
    ):
        await _seed(stream_db)

        await _run_stream(ChatService(stream_db), user_id=USER_CLEAN, message="hoi gi do")

        (state,) = retrieval_graph.states
        assert state["excluded_document_ids"] == []
        assert state["owner_id"] == USER_CLEAN

    async def test_empty_document_ids_keeps_whole_library_semantics(
        self, stream_db, retrieval_graph, generator
    ):
        docs = await _seed(stream_db)

        await _run_stream(
            ChatService(stream_db), user_id=USER_A, message="hoi gi do", document_ids=[]
        )

        (state,) = retrieval_graph.states
        assert state["document_ids"] == []
        assert state["excluded_document_ids"] == [docs["a_off"].id]

    async def test_repo_called_with_retrieval_owner_scope(
        self, stream_db, retrieval_graph, generator, monkeypatch
    ):
        seen: list = []

        async def fake_list(self, owner_id):
            seen.append(owner_id)
            return []

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", fake_list)
        service = ChatService(stream_db)

        await _run_stream(service, user_id=USER_A, message="hoi gi do")
        await _run_stream(service, user_id=ADMIN, message="hoi gi do", is_admin=True)

        assert seen == [USER_A, None]
        assert [s["owner_id"] for s in retrieval_graph.states] == [USER_A, None]

    async def test_db_error_fails_closed_no_retrieval(
        self, stream_db, retrieval_graph, generator, monkeypatch
    ):
        async def boom(self, owner_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", boom)

        events = await _run_stream(ChatService(stream_db), user_id=USER_A, message="hoi gi do")

        assert [e["type"] for e in events] == ["meta", "error"]
        assert retrieval_graph.states == []  # retrieval không được chạy
        generator.assert_not_awaited()  # không sinh câu trả lời nào


# ── State qua LangGraph thật ──────────────────────────────────────────────────


async def test_langgraph_keeps_excluded_document_ids_in_output_state():
    """`excluded_document_ids` là NotRequired trong AgentState: LangGraph thật vẫn phải
    giữ key này từ input tới output (state mà chat_stream đưa tiếp cho generator_node)."""

    async def passthrough(state: AgentState) -> AgentState:
        return {**state, "intent": "rag"}

    graph = StateGraph(AgentState)
    graph.add_node("node", passthrough)
    graph.add_edge(START, "node")
    graph.add_edge("node", END)

    out = await graph.compile().ainvoke(
        {"query": "q", "owner_id": "u1", "excluded_document_ids": ["d9"]}
    )

    assert out["excluded_document_ids"] == ["d9"]
    assert out["owner_id"] == "u1"


# ── Response Cache ────────────────────────────────────────────────────────────


class TestCacheScope:
    def test_no_inactive_docs_keeps_cache_scope_unchanged(self):
        """Không có tài liệu tắt → cache key y hệt trước T10 (không làm mất cache cũ)."""
        ids = ["d1", "d2"]
        assert _cache_document_scope(None, []) is None
        assert _cache_document_scope([], []) == []
        assert _cache_document_scope(ids, []) is ids

    def test_inactive_docs_are_folded_into_cache_scope(self):
        assert _cache_document_scope(None, ["x"]) == ["!x"]
        assert _cache_document_scope(["d1"], ["x", "y"]) == ["d1", "!x", "!y"]

    def test_scope_differs_between_selected_and_excluded_same_id(self):
        """Tài liệu được CHỌN và tài liệu bị LOẠI không được ra cùng một cache key."""
        assert _cache_document_scope(["d1"], []) != _cache_document_scope(None, ["d1"])

    async def test_cache_lookup_and_store_use_exclusion_scope(
        self, db_session, agent_graph, cache_spy
    ):
        docs = await _seed(db_session)
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=USER_A, message="hoi gi do")

        scope = [f"!{docs['a_off'].id}"]
        get.assert_awaited_once_with("hoi gi do", USER_A, scope)
        assert set_.await_args.args[:3] == ("hoi gi do", USER_A, scope)

    async def test_cache_scope_unchanged_for_user_without_inactive_docs(
        self, db_session, agent_graph, cache_spy
    ):
        await _seed(db_session)
        get, set_ = cache_spy

        await ChatService(db_session).chat(
            user_id=USER_CLEAN, message="hoi gi do", document_ids=["d1"]
        )

        get.assert_awaited_once_with("hoi gi do", USER_CLEAN, ["d1"])
        assert set_.await_args.args[:3] == ("hoi gi do", USER_CLEAN, ["d1"])

    async def test_answer_cached_while_doc_active_is_not_served_after_deactivation(
        self, db_session, agent_graph, fake_redis
    ):
        """Ca xấu nhất: tài liệu bị tắt nhưng `bump_version` KHÔNG chạy được (Redis lỗi
        lúc bật/tắt, fail-open). Câu trả lời cache từ lúc tài liệu còn bật không được
        trả lại; pipeline phải chạy lại với danh sách loại trừ."""
        repo = DocumentRepository(db_session)
        doc = await repo.create(name="d.pdf", doc_type=DocumentType.pdf, owner_id=USER_CLEAN)
        await db_session.flush()
        service = ChatService(db_session)

        # Lượt 1: tài liệu còn bật → chạy pipeline, ghi cache.
        await service.chat(user_id=USER_CLEAN, message="cau hoi lap lai")
        # Lượt 2: cache hit thật (đối chứng — cache đang hoạt động).
        await service.chat(user_id=USER_CLEAN, message="cau hoi lap lai")
        assert len(agent_graph.states) == 1

        # Tắt tài liệu, cố ý KHÔNG bump_version.
        await repo.set_active(doc.id, False)

        await service.chat(user_id=USER_CLEAN, message="cau hoi lap lai")

        assert len(agent_graph.states) == 2  # không trả từ cache cũ
        assert agent_graph.states[1]["excluded_document_ids"] == [doc.id]

    async def test_cache_hit_still_served_when_inactive_set_unchanged(
        self, db_session, agent_graph, fake_redis
    ):
        """Không phá cache: tập tài liệu tắt không đổi thì lượt sau vẫn hit."""
        await _seed(db_session)
        service = ChatService(db_session)

        first = await service.chat(user_id=USER_A, message="cau hoi lap lai")
        second = await service.chat(user_id=USER_A, message="cau hoi lap lai")

        assert len(agent_graph.states) == 1
        assert second.message.content == first.message.content
