"""
Generator node: produces final answer with citations.
ONLY answers from retrieved context — never hallucinate.
"""
from app.agents.state import AgentState
from app.llm.factory import get_llm
from app.services.web_search import perform_web_search

SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Answer ONLY based on the provided context.
Rules:
1. If context is insufficient, respond exactly: "Not found in documents."
2. Every claim MUST be supported by a citation [SOURCE: chunk_id]
3. Be concise and professional
4. Do NOT hallucinate or invent information"""

CHITCHAT_PROMPT = """You are a helpful enterprise assistant. Respond to this conversational message naturally.
Message: {query}"""

OUT_OF_SCOPE_RESPONSE = "I'm sorry, this query is outside the scope of the enterprise knowledge system."


def _build_context(state: AgentState) -> tuple[str, list[dict]]:
    chunks = state.get("reranked_results", [])
    if not chunks:
        return "", []

    context_parts = []
    citations = []
    for chunk in chunks:
        context_parts.append(f"[SOURCE: {chunk.chunk_id}]\n{chunk.content}")
        citations.append({
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "document_name": chunk.document_name,
            "content_snippet": chunk.content[:200],
            "score": chunk.score,
        })

    return "\n\n---\n\n".join(context_parts), citations


async def generator_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "rag")

    if intent == "out_of_scope":
        return {**state, "final_answer": OUT_OF_SCOPE_RESPONSE, "citations": []}

    if intent == "chitchat":
        llm = get_llm()
        answer = await llm.chat(
            messages=[
                {"role": "user", "content": CHITCHAT_PROMPT.format(query=state["query"])}],
            temperature=0.7,
            max_tokens=300,
        )
        return {**state, "final_answer": answer, "citations": []}

    # RAG path
    context, citations = _build_context(state)
    has_rag_context = bool(context)

    answer = None
    if has_rag_context:
        llm = get_llm()
        user_message = f"Context:\n{context}\n\nQuestion: {state['query']}"
        answer = await llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.1,
        )

    # Detect if context is empty or LLM says not found
    is_not_found = (
        not has_rag_context
        or not answer
        or "Not found in documents." in answer
        or "Không tìm thấy trong tài liệu." in answer
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
                        f"[SOURCE: web_{idx+1}]\nURL: {r.get('url')}\nTitle: {r.get('title')}\nSnippet: {r.get('snippet')}"
                    )
                web_context = "\n\n---\n\n".join(web_context_parts)

                WEB_SYSTEM_PROMPT = """You are an enterprise knowledge assistant. Answer based on the provided web search context.
Rules:
1. If context is insufficient to answer, respond exactly: "Không tìm thấy trong tài liệu."
2. Be concise and professional
3. Do NOT hallucinate or invent information"""

                llm = get_llm()
                user_message = f"Web Context:\n{web_context}\n\nQuestion: {state['query']}"
                web_answer = await llm.chat(
                    messages=[
                        {"role": "system", "content": WEB_SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.1,
                )

                # Check if web_answer is also not found
                if "Không tìm thấy trong tài liệu." in web_answer or "Not found in documents." in web_answer:
                    return {**state, "final_answer": "Không tìm thấy trong tài liệu.", "citations": []}

                # Add transparency disclaimer prefix
                disclaimer = "Câu trả lời này được tổng hợp từ Internet, không nằm trong tài liệu nội bộ của công ty...\n\n"
                final_answer = disclaimer + web_answer

                web_citations = []
                for idx, r in enumerate(web_results):
                    web_citations.append({
                        "chunk_id": f"web_{idx+1}",
                        "document_id": f"web_{idx+1}",
                        "document_name": r.get("title", "Web Source"),
                        "page_number": None,
                        "section_title": None,
                        "source_link": r.get("url"),
                        "content_snippet": r.get("snippet", "")[:200],
                    })

                return {**state, "final_answer": final_answer, "citations": web_citations}
            else:
                return {**state, "final_answer": "Không tìm thấy trong tài liệu.", "citations": []}
        else:
            return {**state, "final_answer": "Không tìm thấy trong tài liệu.", "citations": []}

    return {**state, "final_answer": answer, "citations": citations}
