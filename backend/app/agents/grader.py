"""
Grader node: evaluates whether retrieved docs are relevant to the query.
If too few relevant docs, sets confidence_score low to trigger rewriter.
"""
from app.agents.state import AgentState
from app.llm.factory import get_llm
from app.rag.reranker import get_reranker

GRADE_PROMPT = """You are grading the relevance of a retrieved document to a user query.
Score: "yes" if the document is relevant, "no" if it is not.
Respond with ONLY "yes" or "no".

Query: {query}
Document: {content}"""


async def grader_node(state: AgentState) -> AgentState:
    llm = get_llm()
    reranker = get_reranker()
    merged = state.get("merged_results", [])

    if not merged:
        return {**state, "reranked_results": [], "confidence_score": 0.0}

    # Re-rank first
    query = state.get("rewritten_query") or state["query"]
    reranked = reranker.rerank(query, merged)

    # Grade top results
    relevant_count = 0
    for chunk in reranked:
        response = await llm.chat(
            messages=[
                {
                    "role": "user",
                    "content": GRADE_PROMPT.format(query=query, content=chunk.content[:500]),
                }
            ],
            temperature=0.0,
            max_tokens=5,
        )
        if response.strip().lower() == "yes":
            relevant_count += 1

    confidence = relevant_count / max(len(reranked), 1)
    return {**state, "reranked_results": reranked, "confidence_score": confidence}
