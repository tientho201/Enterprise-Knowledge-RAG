"""
Generator node: produces final answer with citations.
ONLY answers from retrieved context — never hallucinate.
"""

from app.agents.state import AgentState
from app.llm.base import BaseLLM
from app.llm.factory import get_llm_for_request
from app.services.web_search import perform_web_search

SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Answer ONLY based on the provided context.
Rules:
1. If context is insufficient, respond exactly: "Not found in documents."
2. Every claim MUST be supported by a citation [SOURCE: chunk_id]
3. Be concise and professional
4. Do NOT hallucinate or invent information"""

CHITCHAT_PROMPT = """You are a helpful enterprise assistant. Respond to this conversational message naturally.
Message: {query}"""

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


async def generator_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "rag")

    if intent == "out_of_scope":
        return {**state, "final_answer": OUT_OF_SCOPE_RESPONSE, "citations": []}

    if intent == "chitchat":
        llm = _get_llm(state)
        user_content = _build_user_content(CHITCHAT_PROMPT.format(query=state["query"]), state)
        answer = await llm.chat(
            messages=[{"role": "user", "content": user_content}],
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
        user_text = (
            f"Context:\n{context}\n\nQuestion: {state['query']}"
            if has_rag_context
            else state["query"]
        )
        llm = _get_llm(state)
        system_prompt = state.get("system_prompt") or SYSTEM_PROMPT
        rag_answer = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": _build_user_content(user_text, state)},
            ],
            temperature=0.1,
        )

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

                web_system_prompt = """You are an enterprise knowledge assistant. Answer based on the provided web search context.
Rules:
1. If context is insufficient to answer, respond exactly: "Không tìm thấy trong tài liệu."
2. Be concise and professional
3. Do NOT hallucinate or invent information"""

                llm = _get_llm(state)
                user_message = f"Web Context:\n{web_context}\n\nQuestion: {state['query']}"
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

    return {**state, "final_answer": rag_answer, "citations": citations}
