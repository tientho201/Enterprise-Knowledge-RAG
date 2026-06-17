"""
LangGraph agent graph definition.
Flow: START → Router → [Retriever → Grader → (Rewriter →)* Generator] → END
"""
from langgraph.graph import END, START, StateGraph

from app.agents.generator import generator_node
from app.agents.grader import grader_node
from app.agents.retriever import retriever_node
from app.agents.rewriter import rewriter_node
from app.agents.router import router_node
from app.agents.state import AgentState

MAX_RETRIES = 2


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

    graph.add_node("router", router_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("grader", grader_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("generator", generator_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", should_retrieve, {"retrieve": "retriever", "generate": "generator"})
    graph.add_edge("retriever", "grader")
    graph.add_conditional_edges("grader", should_rewrite, {"rewrite": "rewriter", "generate": "generator"})
    graph.add_edge("rewriter", "retriever")
    graph.add_edge("generator", END)

    return graph


def compile_graph():
    return build_graph().compile()


# Singleton compiled graph
_compiled_graph = None


def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = compile_graph()
    return _compiled_graph
