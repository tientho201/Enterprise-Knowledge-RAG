"""
Generator node: produces final answer with citations.
ONLY answers from retrieved context — never hallucinate.
"""

from app.agents.dlp import check_bulk_extraction
from app.agents.guardrail import BLOCKED_RESPONSE
from app.agents.history import DEFAULT_MAX_CHARS, HISTORY_DEFENSE_RULE, render_history
from app.agents.prompt_defense import INJECTION_DEFENSE_RULE, wrap_untrusted
from app.agents.state import AgentState
from app.llm.base import BaseLLM
from app.llm.factory import get_llm_for_request
from app.services.web_search import perform_web_search

SYSTEM_PROMPT = (
    """You are an enterprise knowledge assistant. Answer ONLY based on the provided context.
Rules:
1. If context is insufficient, respond exactly: "Not found in documents."
2. Every claim MUST be supported by a citation [SOURCE: chunk_id]
3. Be concise and professional
4. Do NOT hallucinate or invent information

"""
    + INJECTION_DEFENSE_RULE
)

CHITCHAT_PROMPT = """You are a helpful enterprise assistant. Respond to this conversational message naturally.
Message: {query}"""

# Chỉ được gửi (thành message system THỨ HAI, ngay sau SYSTEM_PROMPT) khi lượt hỏi có khối
# <history> — SYSTEM_PROMPT ở trên không đổi một byte nào, nên request không có lịch sử y hệt
# trước đây. Lịch sử KHÔNG phải nguồn: câu trả lời cũ còn mang nội dung tài liệu (kể cả tài
# liệu nay đã bị tắt) và chuỗi [SOURCE: ...] cũ; nếu model được phép trả lời/trích dẫn từ đó
# thì bộ lọc tài liệu tắt (excluded_document_ids) bị vòng qua lịch sử.
HISTORY_SYSTEM_PROMPT = (
    """The user message begins with a <history> block holding earlier turns of this conversation.
Rules for conversation history:
1. Use <history> ONLY to understand what the current question in <user_query> refers to. It is NOT a source of answers.
2. Every claim MUST still be supported by the <context> of the current turn, with a citation [SOURCE: chunk_id] whose chunk_id appears in <context>.
3. Do NOT cite, quote or repeat information that appears only in <history>, and never reuse a [SOURCE: ...] marker from it. Earlier answers may rely on documents that are no longer available.
4. If <context> is insufficient, respond exactly: "Not found in documents." even when <history> seems to contain the answer.

"""
    + HISTORY_DEFENSE_RULE
)

# Nhánh chitchat vốn không có message system; chỉ thêm message này khi có khối <history>.
CHITCHAT_HISTORY_SYSTEM_PROMPT = (
    """The user message begins with a <history> block holding earlier turns of this conversation.
Rules for conversation history:
1. Use <history> ONLY to keep the conversation natural and to understand what the current message refers to.
2. Do NOT present information from <history> as facts from company documents, and do NOT output [SOURCE: ...] citations.

"""
    + HISTORY_DEFENSE_RULE
)

OUT_OF_SCOPE_RESPONSE = (
    "I'm sorry, this query is outside the scope of the enterprise knowledge system."
)


def _build_user_content(text: str, state: AgentState) -> str | list[dict]:
    """Dựng content cho message user — string thuần khi không có ảnh (giữ nguyên hành
    vi cũ, regression-safe), mảng multimodal [text, image_url...] khi có ảnh gửi kèm.
    BaseLLM.chat()/stream_chat() nhận thẳng dict này, không cần đổi interface LLM."""
    image_urls = state.get("image_data_urls")
    if not image_urls:
        return text
    return [
        {"type": "text", "text": text},
        *[{"type": "image_url", "image_url": {"url": url}} for url in image_urls],
    ]


def _build_context(state: AgentState) -> tuple[str, list[dict]]:
    chunks = state.get("reranked_results", [])
    if not chunks:
        return "", []

    context_parts = []
    citations = []
    for chunk in chunks:
        context_parts.append(f"[SOURCE: {chunk.chunk_id}]\n{chunk.content}")
        citations.append(
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "document_name": chunk.document_name,
                "page_number": None,
                "section_title": None,
                "source_link": None,
                "content_snippet": chunk.content[:200],
                "score": chunk.score,
            }
        )

    return "\n\n---\n\n".join(context_parts), citations


def _get_llm(state: AgentState) -> BaseLLM:
    """BYOM passthrough: dùng model tùy chỉnh của người dùng nếu có (panel Cấu hình)."""
    return get_llm_for_request(
        model=state.get("model"),
        api_key=state.get("api_key"),
        base_url=state.get("base_url"),
    )


def _history_block(state: AgentState, max_chars: int) -> str:
    """Khối <history> đã bọc untrusted (xem agents/history.py), hoặc "" khi state không có
    lịch sử / không còn lượt hợp lệ nào. Đưa THẲNG state["history"] vào render_history —
    không cắt/strip/nối thêm gì trước đó (bóc marker trích dẫn chỉ kín với nội dung nguyên vẹn).
    """
    return render_history(state.get("history"), max_chars)


def build_rag_messages(
    state: AgentState, context: str, *, history_max_chars: int = DEFAULT_MAX_CHARS
) -> list[dict]:
    """Dựng messages cho lời gọi LLM trả lời RAG. Hàm THUẦN: không I/O, không gọi LLM,
    không sửa `state` — dùng chung cho generator_node (`llm.chat`) và nhánh stream của
    chat_service (`llm.stream_chat`) để hai nơi không lệch nhau.

    Đọc từ state: `query`, `system_prompt`, `history`, `image_data_urls`.
    `context` là chuỗi từ `_build_context(state)`; rỗng → không có khối <context>
    (câu hỏi thuần về ảnh).

    Thứ tự messages:
      1. system  SYSTEM_PROMPT — Lớp 1, bất biến, luôn đứng đầu.
      2. system  HISTORY_SYSTEM_PROMPT — CHỈ khi có khối lịch sử.
      3. system  state["system_prompt"] — Lớp 2 tùy biến từ panel Cấu hình, CỘNG THÊM chứ
         không thay thế (nếu thay thế, safety rules/injection defense của Lớp 1 biến mất
         hoàn toàn khỏi request).
      4. user    <history> → <context> → <user_query> (+ ảnh nếu có).

    Không có lịch sử (history None/rỗng/thiếu key/không còn lượt hợp lệ) → messages y hệt
    trước khi có tính năng lịch sử.
    """
    history_block = _history_block(state, history_max_chars)

    parts: list[str] = []
    if history_block:
        parts.append(history_block)
    if context:
        parts.append(wrap_untrusted("context", context))
    parts.append(wrap_untrusted("user_query", state["query"]))
    user_text = "\n\n".join(parts)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history_block:
        messages.append({"role": "system", "content": HISTORY_SYSTEM_PROMPT})
    developer_prompt = state.get("system_prompt")
    if developer_prompt:
        messages.append({"role": "system", "content": developer_prompt})
    messages.append({"role": "user", "content": _build_user_content(user_text, state)})
    return messages


def build_chitchat_messages(
    state: AgentState, *, history_max_chars: int = DEFAULT_MAX_CHARS
) -> list[dict]:
    """Dựng messages cho nhánh chitchat. Hàm thuần như `build_rag_messages`.

    Không có lịch sử → đúng 1 message user như trước. Có lịch sử → thêm message system
    (CHITCHAT_HISTORY_SYSTEM_PROMPT, có HISTORY_DEFENSE_RULE) và khối <history> đứng
    TRƯỚC CHITCHAT_PROMPT trong message user.
    """
    history_block = _history_block(state, history_max_chars)
    prompt = CHITCHAT_PROMPT.format(query=state["query"])
    if not history_block:
        return [{"role": "user", "content": _build_user_content(prompt, state)}]
    return [
        {"role": "system", "content": CHITCHAT_HISTORY_SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_content(f"{history_block}\n\n{prompt}", state)},
    ]


async def generator_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "rag")

    if intent == "blocked":
        # Guardrail (app/agents/guardrail.py) đã chặn TRƯỚC router — không gọi LLM,
        # tránh cả chi phí lẫn rủi ro model bị dụ trả lời câu injection rõ ràng.
        return {**state, "final_answer": BLOCKED_RESPONSE, "citations": []}

    if intent == "out_of_scope":
        return {**state, "final_answer": OUT_OF_SCOPE_RESPONSE, "citations": []}

    if intent == "chitchat":
        llm = _get_llm(state)
        answer = await llm.chat(
            messages=build_chitchat_messages(state),
            temperature=0.7,
            max_tokens=300,
        )
        return {**state, "final_answer": answer, "citations": []}

    # RAG path
    context, citations = _build_context(state)
    has_rag_context = bool(context)
    has_image = bool(state.get("image_data_urls"))

    rag_answer: str | None = None
    if has_rag_context or has_image:
        # Có ảnh nhưng không có context tài liệu (câu hỏi thuần về ảnh, hoặc retrieval
        # không match gì) → vẫn gọi LLM với ảnh, KHÔNG rơi thẳng vào "not found" chỉ vì
        # thiếu context text — ảnh tự nó đủ để trả lời được nhiều câu hỏi.
        llm = _get_llm(state)
        # Lớp 1 (SYSTEM_PROMPT) + Lớp 2 (system_prompt tùy biến) + lịch sử nếu có — xem
        # build_rag_messages.
        rag_answer = await llm.chat(messages=build_rag_messages(state, context), temperature=0.1)

    # Detect if context/image is empty or LLM says not found
    is_not_found = (
        not (has_rag_context or has_image)
        or not rag_answer
        or "Not found in documents." in rag_answer
        or "Không tìm thấy trong tài liệu." in rag_answer
    )

    if is_not_found:
        if state.get("search_tool"):
            # Execute web search fallback
            query_to_search = state.get("rewritten_query") or state["query"]
            web_results = await perform_web_search(query_to_search)
            if web_results:
                web_context_parts = []
                for idx, r in enumerate(web_results):
                    web_context_parts.append(
                        f"[SOURCE: web_{idx + 1}]\nURL: {r.get('url')}\nTitle: {r.get('title')}\nSnippet: {r.get('snippet')}"
                    )
                web_context = "\n\n---\n\n".join(web_context_parts)

                web_system_prompt = (
                    """You are an enterprise knowledge assistant. Answer based on the provided web search context.
Rules:
1. If context is insufficient to answer, respond exactly: "Không tìm thấy trong tài liệu."
2. Be concise and professional
3. Do NOT hallucinate or invent information

"""
                    + INJECTION_DEFENSE_RULE
                )

                llm = _get_llm(state)
                user_message = (
                    f"{wrap_untrusted('document', web_context)}\n\n"
                    f"{wrap_untrusted('user_query', state['query'])}"
                )
                web_answer = await llm.chat(
                    messages=[
                        {"role": "system", "content": web_system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.1,
                )

                # Check if web_answer is also not found
                if (
                    "Không tìm thấy trong tài liệu." in web_answer
                    or "Not found in documents." in web_answer
                ):
                    return {
                        **state,
                        "final_answer": "Không tìm thấy trong tài liệu.",
                        "citations": [],
                    }

                # Add transparency disclaimer prefix
                disclaimer = "Câu trả lời này được tổng hợp từ Internet, không nằm trong tài liệu nội bộ của công ty...\n\n"
                final_answer = disclaimer + web_answer

                web_citations = []
                for idx, r in enumerate(web_results):
                    web_citations.append(
                        {
                            "chunk_id": f"web_{idx + 1}",
                            "document_id": f"web_{idx + 1}",
                            "document_name": r.get("title", "Web Source"),
                            "page_number": None,
                            "section_title": None,
                            "source_link": r.get("url"),
                            "content_snippet": r.get("snippet", "")[:200],
                        }
                    )

                return {**state, "final_answer": final_answer, "citations": web_citations}
            else:
                return {**state, "final_answer": "Không tìm thấy trong tài liệu.", "citations": []}
        else:
            return {**state, "final_answer": "Không tìm thấy trong tài liệu.", "citations": []}

    # DLP tối thiểu (xem agents/dlp.py) — chỉ log, KHÔNG chặn câu trả lời hợp lệ.
    dlp_result = check_bulk_extraction(rag_answer, state.get("reranked_results", []))
    if dlp_result.flagged:
        import logging

        logging.getLogger(__name__).warning(
            "DLP: possible bulk extraction detected (owner_id=%s): %s",
            state.get("owner_id"),
            dlp_result.reason,
        )

    return {
        **state,
        "final_answer": rag_answer,
        "citations": citations,
        "dlp_flag": dlp_result.flagged,
        "dlp_reason": dlp_result.reason,
    }
