"""
LangGraph agent graph definition.
Flow: START → Guardrail → Router → [Retriever → Grader → (Rewriter →)* Generator] → END
"""

from langgraph.graph import END, START, StateGraph

from app.agents.generator import generator_node
from app.agents.grader import grader_node
from app.agents.guardrail import guardrail_node
from app.agents.retriever import retriever_node
from app.agents.rewriter import rewriter_node
from app.agents.router import router_node
from app.agents.state import AgentState

MAX_RETRIES = 2


def should_route(state: AgentState) -> str:
    """Route after guardrail: blocked → generate (trả lời cố định, không qua router)."""
    if state.get("intent") == "blocked":
        return "generate"
    return "route"


def should_retrieve(state: AgentState) -> str:
    """Route after router: rag → retrieve, others → generate."""
    if state["intent"] == "rag":
        return "retrieve"
    return "generate"


def should_rewrite(state: AgentState) -> str:
    """Route after grader: low confidence + retry budget → rewrite, else → generate."""
    if state["confidence_score"] < 0.3 and state.get("retry_count", 0) < MAX_RETRIES:
        return "rewrite"
    return "generate"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("guardrail", guardrail_node)
    graph.add_node("router", router_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("grader", grader_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("generator", generator_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges(
        "guardrail", should_route, {"route": "router", "generate": "generator"}
    )
    graph.add_conditional_edges(
        "router", should_retrieve, {"retrieve": "retriever", "generate": "generator"}
    )
    graph.add_edge("retriever", "grader")
    graph.add_conditional_edges(
        "grader", should_rewrite, {"rewrite": "rewriter", "generate": "generator"}
    )
    graph.add_edge("rewriter", "retriever")
    graph.add_edge("generator", END)

    return graph


def build_retrieval_graph() -> StateGraph:
    """Graph giống build_graph nhưng DỪNG trước generator (kết thúc ở router/grader).

    Dùng cho luồng SSE streaming: chạy tới đây để có intent + reranked_results,
    rồi stream phần sinh câu trả lời riêng (token-by-token) ngoài graph.
    """
    graph = StateGraph(AgentState)

    graph.add_node("guardrail", guardrail_node)
    graph.add_node("router", router_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("grader", grader_node)
    graph.add_node("rewriter", rewriter_node)

    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges("guardrail", should_route, {"route": "router", "generate": END})
    graph.add_conditional_edges(
        "router", should_retrieve, {"retrieve": "retriever", "generate": END}
    )
    graph.add_edge("retriever", "grader")
    graph.add_conditional_edges("grader", should_rewrite, {"rewrite": "rewriter", "generate": END})
    graph.add_edge("rewriter", "retriever")

    return graph


def compile_graph():
    return build_graph().compile()


# Singleton compiled graphs
_compiled_graph = None
_retrieval_graph = None


def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph


def get_retrieval_graph():
    global _retrieval_graph
    if _retrieval_graph is None:
        _retrieval_graph = build_retrieval_graph().compile()
    return _retrieval_graph
