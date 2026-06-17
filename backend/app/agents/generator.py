"""
Generator node: produces final answer with citations.
ONLY answers from retrieved context — never hallucinate.
"""
from app.agents.state import AgentState
from app.llm.factory import get_llm

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
            messages=[{"role": "user", "content": CHITCHAT_PROMPT.format(query=state["query"])}],
            temperature=0.7,
            max_tokens=300,
        )
        return {**state, "final_answer": answer, "citations": []}

    # RAG path
    context, citations = _build_context(state)
    if not context:
        return {**state, "final_answer": "Not found in documents.", "citations": []}

    llm = get_llm()
    user_message = f"Context:\n{context}\n\nQuestion: {state['query']}"
    answer = await llm.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
    )

    return {**state, "final_answer": answer, "citations": citations}
