"""Router node: classifies query intent as rag | chitchat | out_of_scope."""

from app.agents.state import AgentState
from app.llm.factory import get_llm

ROUTER_PROMPT = """You are a query router for an enterprise knowledge base system.
Classify the user query into one of three categories:
- "rag": The query requires searching internal documents/knowledge base
- "chitchat": General conversation, greetings, small talk
- "out_of_scope": Query is outside the system's purpose (e.g. harmful content)

Respond with ONLY one word: rag, chitchat, or out_of_scope.

Query: {query}"""


async def router_node(state: AgentState) -> AgentState:
    llm = get_llm()
    response = await llm.chat(
        messages=[{"role": "user", "content": ROUTER_PROMPT.format(query=state["query"])}],
        temperature=0.0,
        max_tokens=10,
    )
    intent = response.strip().lower()
    if intent not in ("rag", "chitchat", "out_of_scope"):
        intent = "rag"
    return {**state, "intent": intent}
