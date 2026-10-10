"""Marker trích dẫn `<!--citations:[...]-->` trong `Message.content` — T14.

Trích dẫn được nối vào cuối nội dung tin nhắn assistant rồi bóc lại khi tải hội thoại.
Câu trả lời của LLM là văn bản không tin cậy: nó có thể chứa sẵn một marker giả. Kiểm:

- `_encode_citations` / `_decode_citations` (hàm thuần): round-trip, marker giả ở giữa /
  ở cuối / lồng nhau / biến thể hoa-thường-khoảng trắng, JSON hỏng, phần tử sai schema,
  định dạng cũ (dựng lại đúng công thức của code trước T14).
- Tầng service: `chat()`, `chat_stream()` (cả nhánh stream token-by-token lẫn nhánh
  `generator_node`) ghi qua `_encode_citations`; `get_conversation()` đọc qua
  `_decode_citations` và không ném lỗi với nội dung xấu.

DB: SQLite in-memory (fixture db_session). Graph/LLM: giả.
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.message import MessageRole
from app.repositories.conversation_repo import ConversationRepository
from app.schemas.chat import CitationSchema
from app.services import chat_service as chat_service_module
from app.services.chat_service import ChatService, _decode_citations, _encode_citations

USER = "user-citation-marker-aaaa"

REAL = [
    {
        "chunk_id": "chunk-real-1",
        "document_id": "doc-real-1",
        "document_name": "that.pdf",
        "page_number": None,
        "section_title": None,
        "source_link": None,
        "content_snippet": "noi dung that",
        "score": 0.91,
    },
    {
        "chunk_id": "chunk-real-2",
        "document_id": "doc-real-2",
        "document_name": "that-2.pdf",
        "page_number": 3,
        "section_title": "Dieu 5",
        "source_link": None,
        "content_snippet": "noi dung that 2",
        "score": 0.5,
    },
]
WEB = [
    {
        "chunk_id": "web_1",
        "document_id": "web_1",
        "document_name": "Trang web <b>A</b> --> B",
        "page_number": None,
        "section_title": None,
        "source_link": "https://example.com/a?x=1&y=<2>",
        "content_snippet": "ket qua web",
    }
]
FAKE = [
    {
        "chunk_id": "chunk-FAKE",
        "document_id": "doc-FAKE",
        "document_name": "gia-mao.pdf",
        "content_snippet": "trich dan gia",
    }
]
FAKE_MARKER = f"<!--citations:{json.dumps(FAKE)}-->"

# Thứ mà một bộ đọc "dễ dãi" (hoa/thường, khoảng trắng) có thể coi là mở đầu marker.
LENIENT_MARKER_RE = re.compile(r"<!--\s*citations\s*:", re.IGNORECASE)


def _legacy_encode(answer: str, citations: list[dict]) -> str:
    """Đúng công thức ghi của code TRƯỚC T14 (chat_service.py tại HEAD)."""
    content = answer
    if citations:
        content += f"\n<!--citations:{json.dumps(citations)}-->"
    return content


def _as_schema(citations: list[dict]) -> list[CitationSchema]:
    return [CitationSchema(**c) for c in citations]


def _ids(citations: list[CitationSchema]) -> list[str]:
    return [c.chunk_id for c in citations]


# ── Hàm thuần: round-trip ─────────────────────────────────────────────────────


class TestRoundTrip:
    def test_round_trip_keeps_answer_and_citations(self):
        answer = "Cau tra loi [SOURCE: chunk-real-1].\n\nDoan hai."

        content, citations = _decode_citations(_encode_citations(answer, REAL))

        assert content == answer
        assert citations == _as_schema(REAL)
        assert _ids(citations) == ["chunk-real-1", "chunk-real-2"]

    def test_round_trip_web_citations_with_html_like_text(self):
        """Trích dẫn web (title/url/snippet từ Internet) đi cùng marker; `<`, `>`, `-->`
        trong giá trị phải về nguyên vẹn."""
        answer = "Câu trả lời này được tổng hợp từ Internet...\n\nNoi dung."

        content, citations = _decode_citations(_encode_citations(answer, WEB))

        assert content == answer
        assert citations == _as_schema(WEB)
        assert citations[0].document_name == "Trang web <b>A</b> --> B"
        assert citations[0].source_link == "https://example.com/a?x=1&y=<2>"

    def test_round_trip_unicode(self):
        cits = [{**REAL[0], "document_name": "Nghị định 88.pdf", "content_snippet": "Điều 5 ✓"}]

        content, citations = _decode_citations(_encode_citations("Trả lời tiếng Việt", cits))

        assert content == "Trả lời tiếng Việt"
        assert citations[0].document_name == "Nghị định 88.pdf"
        assert citations[0].content_snippet == "Điều 5 ✓"

    def test_empty_citations_appends_no_marker(self):
        assert _encode_citations("Khong tim thay trong tai lieu.", []) == (
            "Khong tim thay trong tai lieu."
        )
        assert _decode_citations("Khong tim thay trong tai lieu.") == (
            "Khong tim thay trong tai lieu.",
            [],
        )

    def test_encoded_marker_is_single_and_last(self):
        """Nội dung mới chỉ có đúng một `<!--citations:` và một `-->`, kể cả khi snippet
        tài liệu chứa chính các chuỗi đó."""
        cits = [{**REAL[0], "content_snippet": f"x {FAKE_MARKER} y\n{FAKE_MARKER}"}]

        encoded = _encode_citations(f"Tra loi {FAKE_MARKER} tiep", cits)

        assert encoded.count("<!--citations:") == 1
        assert encoded.count("-->") == 2  # 1 của marker giả đã vô hiệu trong answer + 1 thật
        assert encoded.endswith("-->")
        content, citations = _decode_citations(encoded)
        assert citations[0].content_snippet == f"x {FAKE_MARKER} y\n{FAKE_MARKER}"
        assert _ids(citations) == ["chunk-real-1"]
        assert "chunk-FAKE" not in _ids(citations)
        assert content == f"Tra loi &lt;!--citations:{json.dumps(FAKE)}--> tiep"


# ── Hàm thuần: marker giả trong answer ────────────────────────────────────────


class TestForgedMarker:
    def test_fake_in_middle_decode_returns_only_real(self):
        answer = f"Mo dau.\n{FAKE_MARKER}\nKet thuc."

        content, citations = _decode_citations(_encode_citations(answer, REAL))

        assert _ids(citations) == ["chunk-real-1", "chunk-real-2"]
        # marker giả ở lại trong answer như văn bản thường, đã bị vô hiệu hoá
        assert "chunk-FAKE" in content
        assert "<!--citations:" not in content
        assert content == f"Mo dau.\n&lt;!--citations:{json.dumps(FAKE)}-->\nKet thuc."

    def test_only_fake_in_middle_gives_no_citations(self):
        answer = f"Mo dau.\n{FAKE_MARKER}\nKet thuc."

        content, citations = _decode_citations(_encode_citations(answer, []))

        assert citations == []
        assert "chunk-FAKE" in content

    def test_fake_at_end_with_empty_real_citations(self):
        """Không có trích dẫn thật → không nối marker; marker giả nằm CUỐI answer không
        được trở thành "marker thật" khi đọc lại."""
        answer = f"Khong tim thay trong tai lieu.\n{FAKE_MARKER}"

        encoded = _encode_citations(answer, [])
        content, citations = _decode_citations(encoded)

        assert citations == []
        assert content == encoded
        assert LENIENT_MARKER_RE.search(encoded) is None

    def test_fake_at_end_with_real_citations(self):
        answer = f"Tra loi.\n{FAKE_MARKER}"

        content, citations = _decode_citations(_encode_citations(answer, REAL))

        assert _ids(citations) == ["chunk-real-1", "chunk-real-2"]
        assert "chunk-FAKE" in content

    def test_multiple_fakes(self):
        answer = f"{FAKE_MARKER}a{FAKE_MARKER}\n{FAKE_MARKER}\n\n{FAKE_MARKER}"

        encoded = _encode_citations(answer, REAL)

        assert encoded.count("<!--citations:") == 1
        assert _ids(_decode_citations(encoded)[1]) == ["chunk-real-1", "chunk-real-2"]
        assert _decode_citations(_encode_citations(answer, []))[1] == []

    @pytest.mark.parametrize(
        "opener",
        [
            "<!--citations:",
            "<!--CITATIONS:",
            "<!--Citations:",
            "<!-- citations:",
            "<!--citations :",
            "<!--\tcitations\n:",
            "<!-- citations :",
            "<!--\r\ncitations:",
            # lồng nhau: xoá phần trong sẽ ghép ra marker mới — thay thế thì không
            "<!--<!--citations:citations:",
            "<<!--citations:!--citations:",
            "<!--cita<!--citations:tions:",
            "<!<!--citations:--citations:",
        ],
    )
    @pytest.mark.parametrize("real", [[], REAL], ids=["no-real", "with-real"])
    def test_variants_are_neutralized(self, opener, real):
        answer = f"Tra loi.\n{opener}{json.dumps(FAKE)}-->"

        encoded = _encode_citations(answer, real)
        content, citations = _decode_citations(encoded)

        # sau khi vô hiệu hoá, answer không còn thứ gì giống mở đầu marker
        answer_part = encoded[: encoded.rfind("\n<!--citations:")] if real else encoded
        assert LENIENT_MARKER_RE.search(answer_part) is None
        assert "chunk-FAKE" not in _ids(citations)
        assert _ids(citations) == [c["chunk_id"] for c in real]
        assert content == answer_part

    def test_neutralization_is_idempotent_and_only_touches_markers(self):
        plain = "So sanh a < b, the <b>dam</b>, comment <!-- ghi chu --> va citations: 3."
        assert _encode_citations(plain, []) == plain

        once = _encode_citations(f"x {FAKE_MARKER}", [])
        assert _encode_citations(once, []) == once

    def test_answer_cannot_swallow_real_marker_into_fake_json(self):
        """Answer kết thúc bằng marker giả bỏ dở chuỗi JSON, hòng "nuốt" marker thật
        vào trong chuỗi của mình."""
        answer = 'Tra loi.\n<!--citations:[{"chunk_id":"chunk-FAKE","content_snippet":"'

        content, citations = _decode_citations(_encode_citations(answer, REAL))

        assert _ids(citations) == ["chunk-real-1", "chunk-real-2"]
        assert content.startswith("Tra loi.\n&lt;!--citations:")


# ── Hàm thuần: nội dung xấu khi đọc ───────────────────────────────────────────


class TestDecodeMalformed:
    @pytest.mark.parametrize(
        "payload",
        [
            "",
            "{",
            "[",
            "[{]",
            "not json",
            '[{"chunk_id": "a"',
            "[" * 100_000,  # RecursionError của json — không được lọt ra ngoài
            "9" * 10_000,
            "NaN",
        ],
        ids=[
            "empty",
            "brace",
            "bracket",
            "mismatch",
            "text",
            "truncated",
            "deep-nesting",
            "huge-int",
            "nan",
        ],
    )
    def test_broken_json_returns_empty_and_keeps_content(self, payload):
        stored = f"Tra loi.\n<!--citations:{payload}-->"

        content, citations = _decode_citations(stored)

        assert citations == []
        # Quyết định: marker cuối không hợp lệ KHÔNG bị cắt — giữ nguyên chuỗi đã lưu.
        assert content == stored

    @pytest.mark.parametrize(
        "data",
        [
            {"chunk_id": "a"},  # không phải list
            "chuoi",
            123,
            None,
            [1, 2],
            ["a"],
            [None],
            [{}],
            [{"chunk_id": "a"}],  # thiếu field bắt buộc
            [{**FAKE[0], "chunk_id": 123}],  # sai kiểu
            [{**FAKE[0], "page_number": "khong-phai-so"}],
            [{**FAKE[0], "page_number": float("nan")}],
            [REAL[0], {"chunk_id": "a"}],  # 1 phần tử hỏng → bỏ cả danh sách
        ],
    )
    def test_schema_invalid_returns_empty_and_keeps_content(self, data):
        stored = f"Tra loi.\n<!--citations:{json.dumps(data)}-->"

        content, citations = _decode_citations(stored)

        assert citations == []
        assert content == stored

    @pytest.mark.parametrize(
        "stored",
        [
            f"Tra loi.\n{FAKE_MARKER}\nvan con chu phia sau",  # marker không ở cuối
            f"Tra loi.\n{FAKE_MARKER} ",  # khoảng trắng sau marker
            f"Tra loi.\n{FAKE_MARKER}\n",
            f"Tra loi. {FAKE_MARKER}",  # không bắt đầu ở đầu dòng
            f"Tra loi.\n<!--CITATIONS:{json.dumps(FAKE)}-->",
            f"Tra loi.\n<!-- citations:{json.dumps(FAKE)}-->",
            f"Tra loi.\n<!--citations:{json.dumps(FAKE)}--",
            f"Tra loi.\n<!--citations:{json.dumps(FAKE)}",
            f"Tra loi.\n<!--citations:{json.dumps(FAKE, indent=2)}-->".replace(
                '"chunk_id"', '"x": "\n<!--citations:", "chunk_id"'
            ),
            "",
            "-->",
            "\n<!--citations:",
            "\n<!--citations:-->",
        ],
    )
    def test_marker_not_strictly_at_end_is_ignored(self, stored):
        content, citations = _decode_citations(stored)

        assert citations == []
        assert content == stored

    def test_empty_list_marker_is_a_valid_marker(self):
        assert _decode_citations("Tra loi.\n<!--citations:[]-->") == ("Tra loi.", [])


# ── Hàm thuần: định dạng cũ ───────────────────────────────────────────────────


class TestLegacyFormat:
    def test_legacy_content_decodes(self):
        stored = _legacy_encode("Cau tra loi cu.", REAL)

        content, citations = _decode_citations(stored)

        assert content == "Cau tra loi cu."
        assert citations == _as_schema(REAL)

    def test_legacy_web_citations_decode(self):
        web = [{**WEB[0], "document_name": "Trang A", "source_link": "https://example.com/a"}]

        content, citations = _decode_citations(_legacy_encode("Tu Internet...\n\nNoi dung", web))

        assert content == "Tu Internet...\n\nNoi dung"
        assert citations[0].source_link == "https://example.com/a"

    def test_legacy_without_citations(self):
        assert _decode_citations(_legacy_encode("Chao ban!", [])) == ("Chao ban!", [])

    def test_legacy_snippet_containing_marker_text(self):
        """Code cũ dùng regex non-greedy nên snippet chứa `-->` làm hỏng JSON. Bộ đọc
        mới lấy tới hết nội dung nên đọc đúng cả tin nhắn cũ loại này."""
        cits = [{**REAL[0], "content_snippet": f"a --> b {FAKE_MARKER} c\n{FAKE_MARKER}"}]

        content, citations = _decode_citations(_legacy_encode("Cau tra loi cu.", cits))

        assert content == "Cau tra loi cu."
        assert _ids(citations) == ["chunk-real-1"]
        assert citations[0].content_snippet == f"a --> b {FAKE_MARKER} c\n{FAKE_MARKER}"

    def test_legacy_with_forged_marker_before_real_one(self):
        """Tin nhắn cũ đã lưu khi chưa có vô hiệu hoá: marker giả đứng trước marker
        thật. Code cũ trả trích dẫn GIẢ (khớp lần đầu); giờ phải trả trích dẫn thật."""
        stored = _legacy_encode(f"Mo dau.\n{FAKE_MARKER}\nKet thuc.", REAL)

        content, citations = _decode_citations(stored)

        assert _ids(citations) == ["chunk-real-1", "chunk-real-2"]
        assert content == f"Mo dau.\n{FAKE_MARKER}\nKet thuc."

    def test_legacy_with_only_forged_marker_in_middle(self):
        stored = _legacy_encode(f"Mo dau.\n{FAKE_MARKER}\nKet thuc.", [])

        assert _decode_citations(stored) == (stored, [])


# ── Tầng service ──────────────────────────────────────────────────────────────


class FakeGraph:
    def __init__(self, result: dict):
        self.result = result

    async def ainvoke(self, state):
        return {**state, **self.result}


class FakeStreamLLM:
    def __init__(self, tokens: list[str]):
        self.tokens = tokens

    async def stream_chat(self, messages, temperature=0.1):  # noqa: ARG002
        for token in self.tokens:
            yield token


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    monkeypatch.setattr(chat_service_module, "get_cached_answer", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_service_module, "set_cached_answer", AsyncMock())


@pytest.fixture
def stream_db(db_session, monkeypatch):
    """chat_stream tự commit; chặn lại để dữ liệu test không rò sang test khác."""
    monkeypatch.setattr(db_session, "commit", AsyncMock())
    return db_session


def _use_agent_graph(monkeypatch, answer: str, citations: list[dict]) -> None:
    graph = FakeGraph({"final_answer": answer, "citations": citations, "intent": "rag"})
    monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph)


async def _run_stream(service: ChatService, **kwargs) -> list[dict]:
    events = []
    async for raw in service.chat_stream(**kwargs):
        assert raw.startswith("data: ")
        events.append(json.loads(raw[len("data: ") :]))
    return events


async def _stored_assistant_content(db, conv_id: str) -> str:
    conv = await ConversationRepository(db).get_by_id(conv_id, USER)
    assert conv is not None
    (msg,) = [m for m in conv.messages if m.role == MessageRole.assistant]
    return msg.content


async def _reload_assistant(service: ChatService, conv_id: str):
    detail = await service.get_conversation(USER, conv_id)
    (msg,) = [m for m in detail.messages if m.role == MessageRole.assistant]
    return msg


async def _store_raw(db, content: str) -> str:
    """Ghi thẳng một tin nhắn assistant với nội dung tuỳ ý (giả lập dữ liệu đã lưu)."""
    repo = ConversationRepository(db)
    conv = await repo.create(user_id=USER, title="t")
    await repo.add_message(conv.id, MessageRole.user, "hoi")
    await repo.add_message(conv.id, MessageRole.assistant, content)
    return conv.id


class TestChatServiceNonStream:
    async def test_forged_marker_in_answer_reloads_real_citations(self, db_session, monkeypatch):
        answer = f"Mo dau.\n{FAKE_MARKER}\nKet thuc."
        _use_agent_graph(monkeypatch, answer, REAL)
        service = ChatService(db_session)

        res = await service.chat(user_id=USER, message="hoi gi do")

        assert _ids(res.message.citations) == ["chunk-real-1", "chunk-real-2"]
        stored = await _stored_assistant_content(db_session, res.conversation_id)
        assert stored == _encode_citations(answer, REAL)
        assert stored.count("<!--citations:") == 1

        reloaded = await _reload_assistant(service, res.conversation_id)
        assert _ids(reloaded.citations) == ["chunk-real-1", "chunk-real-2"]
        assert "<!--citations:" not in reloaded.content
        assert "chunk-FAKE" in reloaded.content  # hiện ra như văn bản, không bị giấu

    async def test_forged_marker_at_end_without_real_citations(self, db_session, monkeypatch):
        _use_agent_graph(monkeypatch, f"Khong tim thay trong tai lieu.\n{FAKE_MARKER}", [])
        service = ChatService(db_session)

        res = await service.chat(user_id=USER, message="hoi gi do")

        reloaded = await _reload_assistant(service, res.conversation_id)
        assert reloaded.citations == []

    async def test_web_citations_round_trip(self, db_session, monkeypatch):
        answer = "Câu trả lời này được tổng hợp từ Internet...\n\nNoi dung."
        _use_agent_graph(monkeypatch, answer, WEB)
        service = ChatService(db_session)

        res = await service.chat(user_id=USER, message="hoi gi do", search_tool=True)

        reloaded = await _reload_assistant(service, res.conversation_id)
        assert reloaded.content == answer
        assert reloaded.citations == _as_schema(WEB)

    async def test_cache_hit_answer_goes_through_encode(self, db_session, monkeypatch):
        """Response cache lưu answer THÔ + citations; cache hit vẫn phải qua encode."""
        answer = f"Tu cache.\n{FAKE_MARKER}"
        cached = {"final_answer": answer, "citations": REAL, "intent": "rag"}
        monkeypatch.setattr(
            chat_service_module, "get_cached_answer", AsyncMock(return_value=cached)
        )
        graph_factory = AsyncMock()
        monkeypatch.setattr(chat_service_module, "get_agent_graph", lambda: graph_factory)
        service = ChatService(db_session)

        res = await service.chat(user_id=USER, message="hoi gi do")

        graph_factory.ainvoke.assert_not_called()
        stored = await _stored_assistant_content(db_session, res.conversation_id)
        assert stored == _encode_citations(answer, REAL)
        reloaded = await _reload_assistant(service, res.conversation_id)
        assert _ids(reloaded.citations) == ["chunk-real-1", "chunk-real-2"]

    async def test_cache_payload_keeps_raw_answer(self, db_session, monkeypatch):
        answer = f"Tra loi.\n{FAKE_MARKER}"
        _use_agent_graph(monkeypatch, answer, REAL)
        set_ = AsyncMock()
        monkeypatch.setattr(chat_service_module, "set_cached_answer", set_)

        await ChatService(db_session).chat(user_id=USER, message="hoi gi do")

        payload = set_.await_args.args[3]
        assert payload["final_answer"] == answer
        assert payload["citations"] == REAL


class TestChatServiceStream:
    async def test_token_stream_branch_persists_via_encode(self, stream_db, monkeypatch):
        """Nhánh chính của frontend: intent rag + có context → stream token-by-token."""
        chunk = SimpleNamespace(
            chunk_id="chunk-real-1",
            document_id="doc-real-1",
            document_name="that.pdf",
            content="noi dung that",
            score=0.91,
        )
        graph = FakeGraph({"intent": "rag", "reranked_results": [chunk]})
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        # tách marker giả qua nhiều token như khi LLM stream thật
        tokens = ["Mo dau.\n<!--cita", "tions:", json.dumps(FAKE), "-->", "\nKet thuc."]
        monkeypatch.setattr(
            "app.llm.factory.get_llm_for_request", lambda **_: FakeStreamLLM(tokens)
        )
        service = ChatService(stream_db)

        events = await _run_stream(service, user_id=USER, message="hoi gi do")

        assert [e["type"] for e in events] == ["meta", *["delta"] * len(tokens), "done"]
        done = events[-1]
        assert [c["chunk_id"] for c in done["citations"]] == ["chunk-real-1"]
        # client đã nhận nguyên văn marker giả qua delta (không sửa được sau khi gửi)
        streamed = "".join(e["text"] for e in events if e["type"] == "delta")
        assert FAKE_MARKER in streamed

        stored = await _stored_assistant_content(stream_db, done["conversation_id"])
        assert stored.count("<!--citations:") == 1
        reloaded = await _reload_assistant(service, done["conversation_id"])
        assert _ids(reloaded.citations) == ["chunk-real-1"]
        assert reloaded.content == f"Mo dau.\n&lt;!--citations:{json.dumps(FAKE)}-->\nKet thuc."

    async def test_generator_branch_persists_via_encode(self, stream_db, monkeypatch):
        graph = FakeGraph({"intent": "chitchat"})
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        answer = f"Xin chao.\n{FAKE_MARKER}"
        node = AsyncMock(return_value={"final_answer": answer, "citations": []})
        monkeypatch.setattr("app.agents.generator.generator_node", node)
        service = ChatService(stream_db)

        events = await _run_stream(service, user_id=USER, message="chao")

        done = events[-1]
        assert done["type"] == "done"
        assert done["citations"] == []
        stored = await _stored_assistant_content(stream_db, done["conversation_id"])
        assert stored == _encode_citations(answer, [])
        reloaded = await _reload_assistant(service, done["conversation_id"])
        assert reloaded.citations == []

    async def test_generator_branch_web_citations_round_trip(self, stream_db, monkeypatch):
        graph = FakeGraph({"intent": "rag"})  # không có context → generator_node
        monkeypatch.setattr(chat_service_module, "get_retrieval_graph", lambda: graph)
        answer = "Câu trả lời này được tổng hợp từ Internet...\n\nNoi dung."
        node = AsyncMock(return_value={"final_answer": answer, "citations": WEB})
        monkeypatch.setattr("app.agents.generator.generator_node", node)
        service = ChatService(stream_db)

        events = await _run_stream(service, user_id=USER, message="hoi", search_tool=True)

        done = events[-1]
        assert done["citations"] == WEB
        reloaded = await _reload_assistant(service, done["conversation_id"])
        assert reloaded.content == answer
        assert reloaded.citations == _as_schema(WEB)


class TestGetConversation:
    async def test_legacy_stored_message_reads_correctly(self, db_session):
        conv_id = await _store_raw(db_session, _legacy_encode("Cau tra loi cu.", REAL))

        msg = await _reload_assistant(ChatService(db_session), conv_id)

        assert msg.content == "Cau tra loi cu."
        assert msg.citations == _as_schema(REAL)

    async def test_legacy_forged_then_real_returns_real(self, db_session):
        stored = _legacy_encode(f"Mo dau.\n{FAKE_MARKER}\nKet thuc.", REAL)
        conv_id = await _store_raw(db_session, stored)

        msg = await _reload_assistant(ChatService(db_session), conv_id)

        assert _ids(msg.citations) == ["chunk-real-1", "chunk-real-2"]

    @pytest.mark.parametrize(
        "payload",
        ["{broken", '[{"chunk_id": "a"}]', '{"chunk_id": "a"}', "[1]", '[{"chunk_id": 1}]'],
    )
    async def test_bad_marker_does_not_raise(self, db_session, payload):
        """Trước T14: JSON hợp lệ nhưng sai CitationSchema làm MessageResponse ném
        ValidationError → 500 khi tải hội thoại."""
        stored = f"Tra loi.\n<!--citations:{payload}-->"
        conv_id = await _store_raw(db_session, stored)

        msg = await _reload_assistant(ChatService(db_session), conv_id)

        assert msg.citations == []
        assert msg.content == stored

    async def test_user_message_is_never_decoded(self, db_session):
        """Người dùng gõ marker vào câu hỏi: không được thành trích dẫn, không bị cắt."""
        repo = ConversationRepository(db_session)
        conv = await repo.create(user_id=USER, title="t")
        typed = f"cau hoi\n{FAKE_MARKER}"
        await repo.add_message(conv.id, MessageRole.user, typed)

        detail = await ChatService(db_session).get_conversation(USER, conv.id)

        (msg,) = detail.messages
        assert msg.role == MessageRole.user
        assert msg.content == typed
        assert msg.citations == []
