"""ChatService nạp lịch sử hội thoại vào AgentState — T19.

Kiểm ở tầng service, cho CẢ `/chat` (chat) và `/chat/stream` (chat_stream):

- lượt nối tiếp → `state["history"]` là các lượt TRƯỚC (đã bóc marker trích dẫn, KHÔNG
  gồm câu hỏi hiện tại); hội thoại mới / `CHAT_HISTORY_MAX_MESSAGES=0` → `[]`;
- lịch sử được nạp TRƯỚC khi lưu tin nhắn user, sau kiểm tra chủ hội thoại (404);
- `search_tool=true` → không nạp lịch sử (giới hạn tạm thời, xem `_load_history`);
- nạp lịch sử lỗi → chạy tiếp không lịch sử (fail-safe), còn `list_inactive_ids` lỗi
  vẫn fail-closed như T10;
- có lịch sử → không đọc/ghi Response Cache;
- nhánh stream token-by-token dựng messages bằng `build_rag_messages`: không lịch sử
  → y hệt trước T19 (snapshot viết tay), và luôn bằng messages của `/chat`.

Không gọi dịch vụ thật: graph giả, LLM giả, web search giả, cache giả, SQLite in-memory.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select, text

from app.agents import contextualizer as contextualizer_module
from app.agents.generator import (
    HISTORY_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_rag_messages,
    generator_node,
)
from app.agents.state import AgentState
from app.core.config import Settings, settings
from app.models.message import Message, MessageRole
from app.rag.retriever import RetrievedChunk
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.document_repo import DocumentRepository
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService, _encode_citations

OWNER = "user-chat-history-owner"
OTHER = "user-chat-history-other"

Q1 = "Điều 5 quy định gì?"
A1 = "Điều 5 quy định về phạm vi áp dụng. [SOURCE: old-1]"
SNIPPET = "DOAN-TRICH-TAI-LIEU-DA-TAT-9f3a"
# Nội dung THÔ như đã lưu trong DB: câu trả lời + marker trích dẫn chứa snippet tài liệu.
A1_STORED = _encode_citations(
    A1,
    [
        {
            "chunk_id": "old-1",
            "document_id": "doc-old",
            "document_name": "cu.pdf",
            "page_number": None,
            "section_title": None,
            "source_link": None,
            "content_snippet": SNIPPET,
            "score": 0.9,
        }
    ],
)
Q2 = "Còn điều 6 thì sao?"
A2 = "Điều 6 quy định phí dịch vụ là 5%. [SOURCE: c1]"
REWRITTEN = "Điều 6 của quy chế quy định gì?"
TURN_1 = [(MessageRole.user, Q1), (MessageRole.assistant, A1_STORED)]
HISTORY_1 = [{"role": "user", "content": Q1}, {"role": "assistant", "content": A1}]

CHUNKS = [
    RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        document_name="quy-che.pdf",
        content="Điều 6: phí dịch vụ là 5%.",
        score=0.9,
        chunk_index=0,
    ),
    RetrievedChunk(
        chunk_id="c2",
        document_id="d1",
        document_name="quy-che.pdf",
        content="Điều 7: thời hạn 30 ngày.",
        score=0.8,
        chunk_index=1,
    ),
]
RAG_RESULT = {"intent": "rag", "reranked_results": CHUNKS, "confidence_score": 0.8}

# Snapshot VIẾT TAY của message user ở nhánh RAG — không dựng lại bằng hàm đang được kiểm.
USER_CONTENT_NO_HISTORY = (
    "<context>\n"
    "[SOURCE: c1]\n"
    "Điều 6: phí dịch vụ là 5%.\n"
    "\n"
    "---\n"
    "\n"
    "[SOURCE: c2]\n"
    "Điều 7: thời hạn 30 ngày.\n"
    "</context>\n"
    "\n"
    "<user_query>\n"
    "Còn điều 6 thì sao?\n"
    "</user_query>"
)
USER_CONTENT_WITH_HISTORY = (
    "<history>\n"
    '<turn role="user">\n'
    "Điều 5 quy định gì?\n"
    "</turn>\n"
    '<turn role="assistant">\n'
    "Điều 5 quy định về phạm vi áp dụng. [SOURCE: old-1]\n"
    "</turn>\n"
    "</history>\n"
    "\n" + USER_CONTENT_NO_HISTORY
)


# ── Giả lập ───────────────────────────────────────────────────────────────────


class FakeGraph:
    """Thay graph LangGraph: ghi lại state nhận được, trả state + kết quả cố định."""

    def __init__(self, result: dict):
        self.result = result
        self.states: list[dict] = []

    async def ainvoke(self, state):
        self.states.append(dict(state))
        return {**state, **self.result}


class GeneratingGraph(FakeGraph):
    """Graph `/chat` giả: bước truy hồi cố định rồi chạy `generator_node` THẬT (LLM giả)."""

    async def ainvoke(self, state):
        self.states.append(dict(state))
        return await generator_node({**state, **self.result})


class FakeLLM:
    def __init__(self, answer: str = A2):
        self.answer = answer
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"method": "chat", "messages": messages, "kwargs": kwargs})
        return self.answer

    async def stream_chat(self, messages, **kwargs):
        self.calls.append({"method": "stream_chat", "messages": messages, "kwargs": kwargs})
        half = len(self.answer) // 2
        for token in (self.answer[:half], self.answer[half:]):
            yield token


class LLMFactory:
    """Thay `get_llm_for_request`: ghi tham số BYOM, luôn trả cùng một FakeLLM."""

    def __init__(self):
        self.llm = FakeLLM()
        self.requests: list[dict] = []

    def __call__(self, **kwargs):
        self.requests.append(kwargs)
        return self.llm


def _no_real_llm(*args, **kwargs):
    raise AssertionError("LLM mặc định của server không được gọi trong test này")


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    """Không test nào chạm dịch vụ thật; D7 (6 tin nhắn) được ghim, không phụ thuộc .env."""
    monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", 6)
    monkeypatch.setattr("app.llm.factory.get_llm", _no_real_llm)
    monkeypatch.setattr(contextualizer_module, "get_llm", _no_real_llm)
    web = AsyncMock(return_value=[])
    monkeypatch.setattr("app.agents.generator.perform_web_search", web)
    return web


@pytest.fixture
def llm_factory(monkeypatch):
    factory = LLMFactory()
    monkeypatch.setattr("app.llm.factory.get_llm_for_request", factory)
    monkeypatch.setattr("app.agents.generator.get_llm_for_request", factory)
    return factory


@pytest.fixture
def cache_spy(monkeypatch):
    get = AsyncMock(return_value=None)
    set_ = AsyncMock()
    monkeypatch.setattr(chat_service_module, "get_cached_answer", get)
    monkeypatch.setattr(chat_service_module, "set_cached_answer", set_)
    return get, set_


@pytest.fixture
def agent_graph(monkeypatch, cache_spy):
    graph = FakeGraph({"final_answer": A2, "citations": [], "intent": "rag"})
    monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
    return graph


@pytest.fixture
def retrieval_graph(monkeypatch):
    # intent chitchat → chat_stream đi nhánh generator_node (được thay bằng mock `generator`).
    graph = FakeGraph({"intent": "chitchat"})
    monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
    return graph


@pytest.fixture
def generator(monkeypatch):
    node = AsyncMock(return_value={"final_answer": A2, "citations": []})
    monkeypatch.setattr("app.agents.generator.generator_node", node)
    return node


@pytest.fixture
def stream_db(db_session, monkeypatch):
    """chat_stream tự commit; chặn lại để dữ liệu test không rò sang test khác."""
    monkeypatch.setattr(db_session, "commit", AsyncMock())
    return db_session


@pytest.fixture
def repo_calls(monkeypatch):
    """Ghi thứ tự + tham số các lời gọi repo liên quan, vẫn chạy hàm thật."""
    calls: list[tuple] = []
    real_recent = ConversationRepository.list_recent_messages
    real_add = ConversationRepository.add_message

    async def list_recent_messages(self, conversation_id, user_id, limit):
        calls.append(("list_recent_messages", conversation_id, user_id, limit))
        return await real_recent(self, conversation_id, user_id, limit)

    async def add_message(self, conversation_id, role, content):
        calls.append(("add_message", role.value, content))
        return await real_add(self, conversation_id, role, content)

    monkeypatch.setattr(ConversationRepository, "list_recent_messages", list_recent_messages)
    monkeypatch.setattr(ConversationRepository, "add_message", add_message)
    return calls


def _history_loads(calls: list[tuple]) -> list[tuple]:
    return [c for c in calls if c[0] == "list_recent_messages"]


async def _conversation(db, user_id: str, turns: list[tuple[MessageRole, str]]) -> str:
    """Hội thoại có sẵn các tin nhắn `turns`, `created_at` tăng dần tường minh (không phụ
    thuộc độ phân giải đồng hồ)."""
    conv = await ConversationRepository(db).create(user_id=user_id, title="hoi thoai cu")
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index, (role, content) in enumerate(turns):
        db.add(
            Message(
                conversation_id=conv.id,
                role=role,
                content=content,
                created_at=base + timedelta(minutes=index),
            )
        )
    await db.flush()
    return conv.id


async def _stored(db, conversation_id: str) -> list[tuple[str, str]]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return [(m.role.value, m.content) for m in result.scalars().all()]


async def _run_stream(service: ChatService, **kwargs) -> list[dict]:
    events = []
    async for raw in service.chat_stream(**kwargs):
        assert raw.startswith("data: ")
        events.append(json.loads(raw[len("data: ") :]))
    return events


async def _ask(flow: str, db, **kwargs):
    """Chạy một lượt hỏi qua `chat` hoặc `chat_stream`; trả ChatResponse / list event."""
    service = ChatService(db)
    if flow == "chat":
        return await service.chat(**kwargs)
    return await _run_stream(service, **kwargs)


@pytest.fixture(params=["chat", "stream"])
def flow(request, monkeypatch, db_session, cache_spy):
    """Chạy cùng một test cho cả hai luồng. Trả (tên luồng, db, graph giả ghi state)."""
    if request.param == "chat":
        graph = FakeGraph({"final_answer": A2, "citations": [], "intent": "rag"})
        monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)
    else:
        graph = FakeGraph({"intent": "chitchat"})
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        monkeypatch.setattr(
            "app.agents.generator.generator_node",
            AsyncMock(return_value={"final_answer": A2, "citations": []}),
        )
        monkeypatch.setattr(db_session, "commit", AsyncMock())
    return request.param, db_session, graph


# ── Lịch sử vào state ─────────────────────────────────────────────────────────


class TestHistoryInState:
    def test_default_is_six_messages(self):
        """D7 đã duyệt: bật mặc định, 6 tin nhắn gần nhất (đọc mặc định trong code)."""
        assert Settings.model_fields["CHAT_HISTORY_MAX_MESSAGES"].default == 6

    async def test_follow_up_turn_gets_previous_turn(self, flow, repo_calls):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (state,) = graph.states
        assert type(state["history"]) is list
        assert state["history"] == HISTORY_1
        assert _history_loads(repo_calls) == [("list_recent_messages", conv_id, OWNER, 6)]

    async def test_history_has_no_citation_marker_or_snippet(self, flow):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        dumped = json.dumps(graph.states[0]["history"], ensure_ascii=False)
        assert SNIPPET in A1_STORED  # đối chứng: nội dung lưu trong DB CÓ snippet
        assert SNIPPET not in dumped
        assert "citations:" not in dumped

    async def test_current_question_is_not_in_history(self, flow):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (state,) = graph.states
        assert state["query"] == Q2
        assert all(turn["content"] != Q2 for turn in state["history"])
        # Tin nhắn user của lượt này vẫn được lưu (sau khi đã nạp lịch sử).
        assert (await _stored(db, conv_id))[2] == ("user", Q2)

    async def test_history_loaded_before_user_message_is_saved(self, flow, repo_calls):
        name, db, _graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert [c[:2] for c in repo_calls] == [
            ("list_recent_messages", conv_id),
            ("add_message", "user"),
            ("add_message", "assistant"),
        ]

    async def test_two_real_turns_through_the_service(self, flow):
        """Lượt 1 tạo hội thoại qua chính service; lượt 2 thấy đúng lượt 1, không thấy
        câu hỏi của chính nó."""
        name, db, graph = flow

        first = await _ask(name, db, user_id=OWNER, message=Q1)
        conv_id = first.conversation_id if name == "chat" else first[0]["conversation_id"]
        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert graph.states[0]["history"] == []
        assert graph.states[1]["history"] == [
            {"role": "user", "content": Q1},
            {"role": "assistant", "content": A2},
        ]

    async def test_new_conversation_has_empty_history_and_no_lookup(self, flow, repo_calls):
        name, db, graph = flow
        await _conversation(db, OWNER, TURN_1)  # hội thoại KHÁC của cùng user

        await _ask(name, db, user_id=OWNER, message=Q2)

        assert graph.states[0]["history"] == []
        assert _history_loads(repo_calls) == []

    @pytest.mark.parametrize("disabled", [0, -1])
    async def test_setting_zero_disables_history(self, flow, repo_calls, monkeypatch, disabled):
        name, db, graph = flow
        monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", disabled)
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert graph.states[0]["history"] == []
        assert _history_loads(repo_calls) == []

    @pytest.mark.parametrize("limit", [6, 2])
    async def test_only_most_recent_messages_up_to_setting(
        self, flow, repo_calls, monkeypatch, limit
    ):
        name, db, graph = flow
        monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", limit)
        turns = []
        for i in range(5):
            turns += [(MessageRole.user, f"hoi {i}"), (MessageRole.assistant, f"dap {i}")]
        conv_id = await _conversation(db, OWNER, turns)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        expected = [{"role": role.value, "content": content} for role, content in turns]
        assert graph.states[0]["history"] == expected[-limit:]
        assert _history_loads(repo_calls) == [("list_recent_messages", conv_id, OWNER, limit)]

    async def test_history_capped_even_if_repo_returns_too_many(self, flow, monkeypatch):
        """Generator không giới hạn số lượt → service tự cắt lại theo setting."""
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)
        many = [Message(role=MessageRole.user, content=f"tin {i}") for i in range(20)]

        async def too_many(self, conversation_id, user_id, limit):
            return many

        monkeypatch.setattr(ConversationRepository, "list_recent_messages", too_many)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert [t["content"] for t in graph.states[0]["history"]] == [
            f"tin {i}" for i in range(14, 20)
        ]

    async def test_order_kept_without_assuming_alternation(self, flow):
        """Hai request đồng thời xen kẽ u,u,a,a; role `system` bị bỏ (whitelist)."""
        name, db, graph = flow
        conv_id = await _conversation(
            db,
            OWNER,
            [
                (MessageRole.user, "u1"),
                (MessageRole.user, "u2"),
                (MessageRole.system, "he thong"),
                (MessageRole.assistant, "a1"),
                (MessageRole.assistant, "a2"),
                (MessageRole.user, "u3"),
            ],
        )

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert graph.states[0]["history"] == [
            {"role": "user", "content": "u1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
        ]

    async def test_raw_message_objects_reach_to_history_untouched(self, flow, monkeypatch):
        """Bóc marker chỉ kín với nội dung NGUYÊN VẸN: service phải đưa thẳng `Message`
        (content thô, còn marker) vào `to_history`, không biến đổi trước."""
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)
        seen: list = []
        real_to_history = chat_service_module.to_history

        def spy(messages):
            seen.append(list(messages))
            return real_to_history(messages)

        monkeypatch.setattr(chat_service_module, "to_history", spy)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (messages,) = seen
        assert all(type(m) is Message for m in messages)
        assert [(m.role, m.content) for m in messages] == TURN_1
        assert graph.states[0]["history"] == HISTORY_1

    async def test_chat_and_stream_build_the_same_initial_state(
        self, db_session, agent_graph, retrieval_graph, generator, monkeypatch
    ):
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        conv_chat = await _conversation(db_session, OWNER, TURN_1)
        conv_stream = await _conversation(db_session, OWNER, TURN_1)
        kwargs = {
            "user_id": OWNER,
            "message": Q2,
            "document_ids": ["d1"],
            "top_k": 3,
            "similarity_threshold": 0.4,
            "system_prompt": "Trả lời ngắn.",
            "model": "m",
            "api_key": "k",
            "base_url": "http://byom/v1",
            "search_mode": "vector",
        }

        await _ask("chat", db_session, conversation_id=conv_chat, **kwargs)
        await _ask("stream", db_session, conversation_id=conv_stream, **kwargs)

        (chat_state,) = agent_graph.states
        (stream_state,) = retrieval_graph.states
        assert chat_state == stream_state
        assert chat_state["history"] == HISTORY_1
        # Helper dựng state phải đủ MỌI field của AgentState (field mới không bị quên).
        assert set(chat_state) == set(AgentState.__annotations__)

    async def test_stream_state_handed_to_generator_node_keeps_history(
        self, stream_db, retrieval_graph, generator
    ):
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        await _ask("stream", stream_db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (gen_state,) = generator.await_args.args
        assert gen_state["history"] == HISTORY_1
        assert gen_state["query"] == Q2


# ── Cô lập dữ liệu ────────────────────────────────────────────────────────────


class TestIsolation:
    async def test_chat_other_users_conversation_is_404_before_any_history(
        self, db_session, agent_graph, repo_calls
    ):
        conv_id = await _conversation(db_session, OWNER, TURN_1)

        with pytest.raises(HTTPException) as excinfo:
            await ChatService(db_session).chat(user_id=OTHER, message=Q2, conversation_id=conv_id)

        assert excinfo.value.status_code == 404
        assert repo_calls == []  # không nạp lịch sử, không lưu tin nhắn nào
        assert agent_graph.states == []
        assert await _stored(db_session, conv_id) == [(r.value, c) for r, c in TURN_1]

    async def test_stream_other_users_conversation_is_error_before_any_history(
        self, stream_db, retrieval_graph, generator, repo_calls
    ):
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        events = await _run_stream(
            ChatService(stream_db), user_id=OTHER, message=Q2, conversation_id=conv_id
        )

        assert events == [{"type": "error", "detail": "Conversation not found"}]
        assert repo_calls == []
        assert retrieval_graph.states == []
        generator.assert_not_awaited()

    async def test_load_history_itself_enforces_owner(self, db_session):
        """Lớp thứ hai: kể cả khi bị gọi thẳng, lịch sử của hội thoại người khác là rỗng."""
        conv_id = await _conversation(db_session, OWNER, TURN_1)
        service = ChatService(db_session)

        assert await service._load_history(conv_id, OTHER, False) == []
        assert await service._load_history(conv_id, OWNER, False) == HISTORY_1


# ── search_tool=true: không nạp lịch sử (giới hạn tạm thời) ───────────────────


class TestWebSearchDisablesHistory:
    async def test_search_tool_request_gets_no_history_and_no_lookup(self, flow, repo_calls):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id, search_tool=True)

        (state,) = graph.states
        assert state["search_tool"] is True
        assert state["history"] == []
        assert _history_loads(repo_calls) == []

    @pytest.mark.parametrize("search_tool", [False, None])
    async def test_history_loaded_when_search_tool_is_off(self, flow, search_tool):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        await _ask(
            name, db, user_id=OWNER, message=Q2, conversation_id=conv_id, search_tool=search_tool
        )

        assert graph.states[0]["history"] == HISTORY_1

    async def test_contextualizer_does_nothing_for_search_tool_state(self, flow):
        """History rỗng → contextualizer THẬT trả nguyên state, không gọi LLM → không có
        `rewritten_query` nào mang nội dung lịch sử."""
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)
        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id, search_tool=True)
        (state,) = graph.states

        out = await contextualizer_module.contextualizer_node(state)  # get_llm → AssertionError

        assert out is state
        assert out["rewritten_query"] is None

    async def test_web_search_receives_only_the_original_question(
        self, stream_db, monkeypatch, isolation, llm_factory
    ):
        """Luồng stream, không tìm thấy chunk nào → generator_node THẬT rơi vào web
        search: truy vấn gửi ra ngoài là câu người dùng gõ, không có gì từ lịch sử."""
        graph = FakeGraph({"intent": "rag", "reranked_results": []})
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        events = await _run_stream(
            ChatService(stream_db),
            user_id=OWNER,
            message=Q2,
            conversation_id=conv_id,
            search_tool=True,
        )

        assert [e["type"] for e in events] == ["meta", "delta", "done"]
        isolation.assert_awaited_once_with(Q2)
        assert llm_factory.llm.calls == []


# ── Nạp lịch sử lỗi: fail-safe; tài liệu tắt: vẫn fail-closed ─────────────────


class TestHistoryLoadFailure:
    async def test_error_means_no_history_and_request_still_answers(
        self, flow, monkeypatch, caplog
    ):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        async def boom(self, conversation_id, user_id, limit):
            raise RuntimeError(f"db down while reading {Q1}")

        monkeypatch.setattr(ConversationRepository, "list_recent_messages", boom)

        with caplog.at_level(logging.WARNING, logger="app.services.chat_service"):
            result = await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (state,) = graph.states
        assert state["history"] == []
        assert state["query"] == Q2
        if name == "chat":
            assert result.message.content == A2
        else:
            assert [e["type"] for e in result] == ["meta", "delta", "done"]
        assert (await _stored(db, conv_id))[2:] == [("user", Q2), ("assistant", A2)]
        (record,) = [r for r in caplog.records if r.name == "app.services.chat_service"]
        assert record.levelno == logging.WARNING
        assert "RuntimeError" in record.getMessage()
        # Không log nội dung (thông điệp lỗi có thể mang câu hỏi/lịch sử), không traceback.
        assert Q1 not in record.getMessage()
        assert record.exc_info is None

    async def test_sql_error_is_contained_in_a_savepoint(self, flow, monkeypatch, test_engine):
        """Câu SQL nạp lịch sử lỗi thật: phải nằm trong SAVEPOINT và được rollback về đó,
        để transaction của request còn dùng được (Postgres huỷ cả transaction nếu không)."""
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        async def bad_sql(self, conversation_id, user_id, limit):
            await self.db.execute(text("SELECT * FROM t19_no_such_table"))

        monkeypatch.setattr(ConversationRepository, "list_recent_messages", bad_sql)
        event.listen(test_engine.sync_engine, "before_cursor_execute", record)
        try:
            await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)
        finally:
            event.remove(test_engine.sync_engine, "before_cursor_execute", record)

        failing = next(i for i, s in enumerate(statements) if "t19_no_such_table" in s)
        assert statements[failing - 1].startswith("SAVEPOINT ")
        assert statements[failing + 1].startswith("ROLLBACK TO SAVEPOINT ")
        assert graph.states[0]["history"] == []
        assert (await _stored(db, conv_id))[2:] == [("user", Q2), ("assistant", A2)]

    async def test_inactive_docs_error_still_fails_closed_chat(
        self, db_session, agent_graph, cache_spy, monkeypatch
    ):
        """Fail-safe của lịch sử KHÔNG lan sang bộ lọc tài liệu tắt (T10)."""
        conv_id = await _conversation(db_session, OWNER, TURN_1)

        async def boom(self, owner_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", boom)

        with pytest.raises(RuntimeError, match="db down"):
            await ChatService(db_session).chat(user_id=OWNER, message=Q2, conversation_id=conv_id)

        get, set_ = cache_spy
        assert agent_graph.states == []
        get.assert_not_awaited()
        set_.assert_not_awaited()

    async def test_inactive_docs_error_still_fails_closed_stream(
        self, stream_db, retrieval_graph, generator, monkeypatch
    ):
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        async def boom(self, owner_id):
            raise RuntimeError("db down")

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", boom)

        events = await _run_stream(
            ChatService(stream_db), user_id=OWNER, message=Q2, conversation_id=conv_id
        )

        assert [e["type"] for e in events] == ["meta", "error"]
        assert retrieval_graph.states == []
        generator.assert_not_awaited()

    async def test_excluded_document_ids_unaffected_by_history(self, flow, monkeypatch):
        name, db, graph = flow
        conv_id = await _conversation(db, OWNER, TURN_1)

        async def inactive(self, owner_id):
            return ["doc-tat"]

        monkeypatch.setattr(DocumentRepository, "list_inactive_ids", inactive)

        await _ask(name, db, user_id=OWNER, message=Q2, conversation_id=conv_id)

        (state,) = graph.states
        assert state["excluded_document_ids"] == ["doc-tat"]
        assert state["owner_id"] == OWNER
        assert state["history"] == HISTORY_1


# ── Response Cache ────────────────────────────────────────────────────────────


class TestCache:
    async def test_turn_with_history_never_reads_or_writes_cache(
        self, db_session, agent_graph, cache_spy
    ):
        conv_id = await _conversation(db_session, OWNER, TURN_1)
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=OWNER, message=Q2, conversation_id=conv_id)

        get.assert_not_awaited()
        set_.assert_not_awaited()
        assert len(agent_graph.states) == 1

    async def test_cached_answer_of_same_text_is_not_served_to_follow_up(
        self, db_session, agent_graph, cache_spy
    ):
        """Cache đang có sẵn câu trả lời cho đúng câu chữ này (từ hội thoại khác): lượt
        nối tiếp vẫn phải chạy pipeline với lịch sử của chính nó."""
        conv_id = await _conversation(db_session, OWNER, TURN_1)
        get, _set = cache_spy
        get.return_value = {"final_answer": "tra loi cua hoi thoai khac", "citations": []}

        response = await ChatService(db_session).chat(
            user_id=OWNER, message=Q2, conversation_id=conv_id
        )

        assert response.message.content == A2
        assert len(agent_graph.states) == 1

    async def test_new_conversation_still_uses_cache(self, db_session, agent_graph, cache_spy):
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=OWNER, message=Q2)

        get.assert_awaited_once_with(Q2, OWNER, None)
        assert set_.await_args.args[:3] == (Q2, OWNER, None)

    async def test_existing_conversation_without_history_still_uses_cache(
        self, db_session, agent_graph, cache_spy, monkeypatch
    ):
        """Không có lịch sử trong state (hội thoại chưa có tin nào / setting = 0) → hành
        vi cache y hệt trước T19."""
        get, set_ = cache_spy
        empty_conv = await _conversation(db_session, OWNER, [])
        service = ChatService(db_session)

        await service.chat(user_id=OWNER, message=Q2, conversation_id=empty_conv)
        monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", 0)
        conv_id = await _conversation(db_session, OWNER, TURN_1)
        await service.chat(user_id=OWNER, message=Q2, conversation_id=conv_id)

        assert get.await_count == 2
        assert set_.await_count == 2

    @pytest.mark.parametrize("search_mode", ["vector", "keyword", "advanced"])
    async def test_search_mode_rule_from_t22_still_applies(
        self, db_session, agent_graph, cache_spy, search_mode
    ):
        get, set_ = cache_spy

        await ChatService(db_session).chat(user_id=OWNER, message=Q2, search_mode=search_mode)

        get.assert_not_awaited()
        set_.assert_not_awaited()


# ── Nhánh stream token-by-token ───────────────────────────────────────────────


@pytest.fixture
def rag_stream(monkeypatch, llm_factory):
    """`/chat/stream` đi nhánh fast-path: intent rag, có context, không ảnh."""
    graph = FakeGraph(dict(RAG_RESULT))
    monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
    return graph


class TestStreamFastPath:
    async def test_no_history_messages_are_byte_identical_to_before(
        self, stream_db, rag_stream, llm_factory
    ):
        events = await _run_stream(ChatService(stream_db), user_id=OWNER, message=Q2)

        (call,) = llm_factory.llm.calls
        assert call["method"] == "stream_chat"
        assert call["kwargs"] == {"temperature": 0.1}
        assert call["messages"] == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_CONTENT_NO_HISTORY},
        ]
        assert [e["type"] for e in events] == ["meta", "delta", "delta", "done"]
        assert "".join(e["text"] for e in events if e["type"] == "delta") == A2

    async def test_no_history_custom_system_prompt_is_last_system_message(
        self, stream_db, rag_stream, llm_factory
    ):
        await _run_stream(
            ChatService(stream_db), user_id=OWNER, message=Q2, system_prompt="Trả lời ngắn."
        )

        assert llm_factory.llm.calls[0]["messages"] == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "Trả lời ngắn."},
            {"role": "user", "content": USER_CONTENT_NO_HISTORY},
        ]

    @pytest.mark.parametrize("empty_prompt", [None, ""])
    async def test_no_history_empty_system_prompt_adds_nothing(
        self, stream_db, rag_stream, llm_factory, empty_prompt
    ):
        await _run_stream(
            ChatService(stream_db), user_id=OWNER, message=Q2, system_prompt=empty_prompt
        )

        assert [m["role"] for m in llm_factory.llm.calls[0]["messages"]] == ["system", "user"]
        assert llm_factory.llm.calls[0]["messages"][1]["content"] == USER_CONTENT_NO_HISTORY

    @pytest.mark.parametrize("case", ["setting_zero", "search_tool", "load_error"])
    async def test_existing_conversation_without_history_is_also_identical(
        self, stream_db, rag_stream, llm_factory, monkeypatch, case
    ):
        conv_id = await _conversation(stream_db, OWNER, TURN_1)
        kwargs = {}
        if case == "setting_zero":
            monkeypatch.setattr(settings, "CHAT_HISTORY_MAX_MESSAGES", 0)
        elif case == "search_tool":
            kwargs["search_tool"] = True
        else:
            monkeypatch.setattr(
                ConversationRepository,
                "list_recent_messages",
                AsyncMock(side_effect=RuntimeError("db down")),
            )

        await _run_stream(
            ChatService(stream_db), user_id=OWNER, message=Q2, conversation_id=conv_id, **kwargs
        )

        assert llm_factory.llm.calls[0]["messages"] == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_CONTENT_NO_HISTORY},
        ]

    async def test_with_history_exact_messages(self, stream_db, rag_stream, llm_factory):
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        await _run_stream(
            ChatService(stream_db),
            user_id=OWNER,
            message=Q2,
            conversation_id=conv_id,
            system_prompt="Trả lời ngắn.",
        )

        messages = llm_factory.llm.calls[0]["messages"]
        assert messages == [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": HISTORY_SYSTEM_PROMPT},
            {"role": "system", "content": "Trả lời ngắn."},
            {"role": "user", "content": USER_CONTENT_WITH_HISTORY},
        ]
        assert SNIPPET not in json.dumps(messages, ensure_ascii=False)

    async def test_byom_arguments_passed_through_unchanged(
        self, stream_db, rag_stream, llm_factory
    ):
        await _run_stream(
            ChatService(stream_db),
            user_id=OWNER,
            message=Q2,
            model="m-x",
            api_key="k-x",
            base_url="http://byom/v1",
        )

        assert llm_factory.requests == [
            {"model": "m-x", "api_key": "k-x", "base_url": "http://byom/v1"}
        ]

    async def test_user_query_is_the_original_question_not_the_rewritten_one(
        self, stream_db, monkeypatch, llm_factory
    ):
        """Contextualizer/rewriter chỉ ghi `rewritten_query` (dùng cho truy hồi); câu được
        trả lời và câu được lưu vẫn là câu người dùng gõ."""
        graph = FakeGraph({**RAG_RESULT, "rewritten_query": REWRITTEN})
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        conv_id = await _conversation(stream_db, OWNER, TURN_1)

        events = await _run_stream(
            ChatService(stream_db), user_id=OWNER, message=Q2, conversation_id=conv_id
        )

        messages = llm_factory.llm.calls[0]["messages"]
        assert messages[-1]["content"] == USER_CONTENT_WITH_HISTORY
        assert REWRITTEN not in json.dumps(messages, ensure_ascii=False)
        assert (await _stored(stream_db, conv_id))[2] == ("user", Q2)
        assert (await _stored(stream_db, conv_id))[3][0] == "assistant"
        assert (await _stored(stream_db, conv_id))[3][1].startswith(A2)
        assert "".join(e["text"] for e in events if e["type"] == "delta") == A2

    def test_build_rag_messages_reads_query_not_rewritten_query(self):
        """Khoá hợp đồng của hàm mà nhánh stream dựa vào (review T18: chưa test nào khoá)."""
        state = {
            "query": Q2,
            "rewritten_query": REWRITTEN,
            "system_prompt": None,
            "history": [],
            "image_data_urls": [],
        }

        messages = build_rag_messages(state, "ngu canh")  # type: ignore[arg-type]

        assert messages[-1]["content"] == (
            "<context>\nngu canh\n</context>\n\n<user_query>\nCòn điều 6 thì sao?\n</user_query>"
        )


# ── /chat và /chat/stream cho cùng messages ───────────────────────────────────


class TestChatAndStreamAgree:
    @pytest.mark.parametrize("with_history", [True, False])
    @pytest.mark.parametrize("system_prompt", [None, "Trả lời ngắn."])
    async def test_same_input_gives_same_llm_messages(
        self, db_session, monkeypatch, cache_spy, llm_factory, with_history, system_prompt
    ):
        monkeypatch.setattr(db_session, "commit", AsyncMock())
        result = {**RAG_RESULT, "rewritten_query": REWRITTEN}
        agent = GeneratingGraph(result)
        retrieval = FakeGraph(result)
        monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: agent)
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: retrieval)
        turns = TURN_1 if with_history else []
        conv_chat = await _conversation(db_session, OWNER, turns)
        conv_stream = await _conversation(db_session, OWNER, turns)
        kwargs = {"user_id": OWNER, "message": Q2, "system_prompt": system_prompt}

        response = await _ask("chat", db_session, conversation_id=conv_chat, **kwargs)
        events = await _ask("stream", db_session, conversation_id=conv_stream, **kwargs)

        chat_call, stream_call = llm_factory.llm.calls
        assert (chat_call["method"], stream_call["method"]) == ("chat", "stream_chat")
        assert chat_call["messages"] == stream_call["messages"]
        assert chat_call["kwargs"] == stream_call["kwargs"] == {"temperature": 0.1}
        expected_user = USER_CONTENT_WITH_HISTORY if with_history else USER_CONTENT_NO_HISTORY
        assert chat_call["messages"][-1] == {"role": "user", "content": expected_user}
        # Câu được lưu và câu được trả lời là câu GỐC ở cả hai luồng.
        first_new = len(turns)
        for conv_id in (conv_chat, conv_stream):
            stored = await _stored(db_session, conv_id)
            assert stored[first_new] == ("user", Q2)
            assert stored[first_new + 1][1].startswith(A2)
        assert response.message.content == A2
        assert "".join(e["text"] for e in events if e["type"] == "delta") == A2
        assert [c.chunk_id for c in response.message.citations] == ["c1", "c2"]
        assert [c["chunk_id"] for c in events[-1]["citations"]] == ["c1", "c2"]
