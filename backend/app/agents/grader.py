"""
Grader node: evaluates whether retrieved docs are relevant to the query.
If too few relevant docs, sets confidence_score low to trigger rewriter.

Tối ưu độ trễ: chấm điểm TẤT CẢ chunk trong MỘT lần gọi LLM (batch) thay vì mỗi
chunk một lần — trước đây tới 5 round-trip tuần tự, giờ chỉ 1. Cắt phần lớn thời
gian chờ của mỗi truy vấn.
"""

import re

from app.agents.state import AgentState
from app.llm.factory import get_llm
from app.rag.reranker import get_reranker

BATCH_GRADE_PROMPT = """You are grading the relevance of retrieved documents to a user query.
For each numbered document, decide if it is relevant to answering the query.
Return ONLY the numbers of the relevant documents separated by commas (e.g. "1,3,4").
If none are relevant, return exactly "none".

Query: {query}

Documents:
{docs}"""


async def grader_node(state: AgentState) -> AgentState:
    reranker = get_reranker()
    merged = state.get("merged_results", [])

    if not merged:
        return {**state, "reranked_results": [], "confidence_score": 0.0}

    # Re-rank first (hybrid score — không gọi LLM). top_k từ UI override RERANK_TOP_K.
    query = state.get("rewritten_query") or state["query"]
    reranked = reranker.rerank(query, merged, top_k=state.get("top_k"))

    # Chấm điểm cả lô trong 1 lần gọi LLM
    docs_block = "\n\n".join(f"{i + 1}. {chunk.content[:500]}" for i, chunk in enumerate(reranked))
    llm = get_llm()
    response = await llm.chat(
        messages=[
            {"role": "user", "content": BATCH_GRADE_PROMPT.format(query=query, docs=docs_block)}
        ],
        temperature=0.0,
        max_tokens=30,
    )

    # Parse các số hợp lệ (1..len) từ câu trả lời; "none" → 0 relevant
    relevant = {
        n for n in (int(x) for x in re.findall(r"\d+", response)) if 1 <= n <= len(reranked)
    }
    confidence = len(relevant) / max(len(reranked), 1)
    return {**state, "reranked_results": reranked, "confidence_score": confidence}
