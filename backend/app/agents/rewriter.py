"""Rewriter node: rewrites user query for better retrieval when grader rejects."""

from app.agents.prompt_defense import INJECTION_DEFENSE_RULE, wrap_untrusted
from app.agents.state import AgentState
from app.llm.factory import get_llm

REWRITE_SYSTEM_PROMPT = (
    """You are an expert at improving search queries for a document retrieval system.
Rewrite the following query to be more specific and likely to retrieve relevant documents.
Respond with ONLY the improved query, no explanations.

"""
    + INJECTION_DEFENSE_RULE
)


async def rewriter_node(state: AgentState) -> AgentState:
    llm = get_llm()
    response = await llm.chat(
        messages=[
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": wrap_untrusted("user_query", state["query"])},
        ],
        temperature=0.3,
        max_tokens=200,
    )
    return {
        **state,
        "rewritten_query": response.strip(),
        "retry_count": state.get("retry_count", 0) + 1,
    }
