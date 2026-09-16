"""Router node: classifies query intent as rag | chitchat | out_of_scope."""

from app.agents.prompt_defense import INJECTION_DEFENSE_RULE, wrap_untrusted
from app.agents.state import AgentState
from app.llm.factory import get_llm

ROUTER_SYSTEM_PROMPT = (
    """You are a query router for an enterprise knowledge base system.
Classify the user query into one of three categories:
- "rag": The query requires searching internal documents/knowledge base
- "chitchat": General conversation, greetings, small talk
- "out_of_scope": Query is outside the system's purpose (e.g. harmful content)

Respond with ONLY one word: rag, chitchat, or out_of_scope.

"""
    + INJECTION_DEFENSE_RULE
)


async def router_node(state: AgentState) -> AgentState:
    llm = get_llm()
    response = await llm.chat(
        messages=[
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": wrap_untrusted("user_query", state["query"])},
        ],
        temperature=0.0,
        max_tokens=10,
    )
    intent = response.strip().lower()
    if intent not in ("rag", "chitchat", "out_of_scope"):
        intent = "rag"
    # Router chỉ thấy text query, không biết có ảnh gửi kèm — nếu lỡ phân loại
    # out_of_scope, ảnh sẽ bị bỏ hoàn toàn (generator trả OUT_OF_SCOPE_RESPONSE, không
    # gọi LLM). Có ảnh → ép về "rag" tối thiểu, generator_node đã xử lý được cả trường
    # hợp không có context tài liệu (trả lời thuần từ ảnh) lẫn có context.
    if intent == "out_of_scope" and state.get("image_data_urls"):
        intent = "rag"
    return {**state, "intent": intent}
