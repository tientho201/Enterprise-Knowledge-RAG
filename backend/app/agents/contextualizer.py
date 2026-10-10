"""Contextualizer node: viết lại câu hỏi nối tiếp thành câu hỏi độc lập trước khi truy hồi.

Câu hỏi nối tiếp ("còn điều 6 thì sao?", "nó áp dụng cho ai?") không đủ nghĩa để tìm
kiếm vector. Node này dùng lịch sử hội thoại (`state["history"]`) để viết lại thành một
câu tự đủ nghĩa và ghi vào `state["rewritten_query"]` — trường mà retriever/grader đã
ưu tiên đọc. `state["query"]` KHÔNG BAO GIỜ bị thay: generator trả lời đúng câu người
dùng gõ.

Hợp đồng:

- Không có lịch sử dùng được → trả NGUYÊN state (cùng object), KHÔNG gọi LLM: lượt đầu
  của hội thoại không tốn thêm chi phí/độ trễ.
- Có lịch sử → đúng 1 lời gọi LLM qua `get_llm()` (model mặc định của server; BYOM cho
  node này là việc của task sau).
- Mọi thất bại (LLM lỗi, quá thời gian, trả rỗng, trả thứ không giống một câu hỏi) →
  trả nguyên state. Node này là tối ưu truy hồi, không được làm hỏng cả request.

Đầu vào lẫn đầu ra đều KHÔNG tin cậy:

- Lịch sử: `render_history` đã bóc marker trích dẫn, whitelist role và vô hiệu hoá tag.
- Câu hỏi: `wrap_untrusted` không escape gì nên tag trong câu hỏi được vô hiệu hoá ở
  đây trước khi bọc (cùng cơ chế với lịch sử).
- Đầu ra LLM sẽ thành câu truy vấn (và được grader bọc lại trong tag câu hỏi): xem
  `_clean_rewritten`.
"""

import asyncio
import logging

# `_neutralize_tags` là hàm private của history.py nhưng là NGUỒN DUY NHẤT của danh sách
# tag untrusted; cài đặt lại ở đây sẽ lệch khi danh sách đổi. test_contextualizer.py khoá
# hành vi này qua prompt thật, nên đổi tên/hành vi bên history.py sẽ làm test đỏ.
from app.agents.history import (
    DEFAULT_MAX_CHARS,
    HISTORY_DEFENSE_RULE,
    _neutralize_tags,
    render_history,
)
from app.agents.prompt_defense import INJECTION_DEFENSE_RULE, wrap_untrusted
from app.agents.state import AgentState
from app.llm.factory import get_llm

logger = logging.getLogger(__name__)

# Số lượt gần nhất tối đa đưa vào prompt. `render_history` chỉ giới hạn theo ký tự nội
# dung (không tính tag bọc, không giới hạn số lượt), nên chặn thêm ở đây để prompt có
# trần kể cả khi nơi nạp `history` không giới hạn.
MAX_HISTORY_TURNS = 10
# Ngân sách ký tự nội dung lịch sử — phải là int (render_history không nhận None/float).
HISTORY_MAX_CHARS: int = DEFAULT_MAX_CHARS
# Câu hỏi dài hơn mức này coi như đã tự đủ nghĩa → không viết lại. Với max_tokens=200
# bản viết lại của một câu rất dài sẽ bị cắt cụt và truy hồi kém hơn chính câu gốc.
MAX_QUESTION_CHARS = 1000
# Trần độ dài đầu ra được chấp nhận. Vượt → không phải một câu hỏi tìm kiếm → bỏ.
MAX_REWRITTEN_CHARS = 500
MAX_TOKENS = 200
# Trần thời gian cho riêng lời gọi này: quá hạn thì truy hồi bằng câu gốc thay vì bắt
# người dùng chờ một bước tối ưu.
LLM_TIMEOUT_SECONDS = 15.0

CONTEXTUALIZE_SYSTEM_PROMPT = (
    """You rewrite follow-up questions for a document retrieval system.
You are given the previous conversation turns and the user's current question.
Rewrite the current question as ONE standalone question that can be understood without
the conversation: resolve pronouns and references ("it", "that", "the one above",
"còn cái đó thì sao") using the conversation.

Rules:
1. If the current question is already standalone, return it unchanged.
2. Keep the same language as the current question. Do not translate.
3. Do NOT answer the question. Do NOT add facts that are not in the conversation.
4. Respond with ONLY the rewritten question on a single line, no explanations, no tags.

"""
    + INJECTION_DEFENSE_RULE
    + "\n"
    + HISTORY_DEFENSE_RULE
)

# Đoạn mở đầu của từng phần system prompt: xuất hiện trong đầu ra = model đang chép lại
# prompt chứ không viết câu hỏi.
_PROMPT_ECHO_MARKERS: tuple[str, ...] = (
    CONTEXTUALIZE_SYSTEM_PROMPT[:40],
    INJECTION_DEFENSE_RULE[:40],
    HISTORY_DEFENSE_RULE[:40],
)


def _clean_rewritten(response: object, original: str) -> str | None:
    """Chuẩn hoá đầu ra LLM thành câu truy vấn; trả None nếu không dùng được.

    Đầu ra LLM là dữ liệu không tin cậy (chịu tác động của lịch sử và câu hỏi). Chỉ
    nhận khi nó trông như MỘT câu hỏi tìm kiếm:

    - phải là str, không rỗng sau khi gộp khoảng trắng (nhiều dòng → một dòng);
    - không dài quá `MAX_REWRITTEN_CHARS` (không cắt bớt: bản cắt cụt tệ hơn câu gốc);
    - không chứa tag untrusted nào (`<history>`, `<turn>`, tag câu hỏi...): model chép
      lại prompt, hoặc đang cố đóng tag ở node sau (grader bọc câu truy vấn trong tag);
    - không chứa đoạn mở đầu của system prompt;
    - khác câu gốc (giống hệt → không có gì để ghi).
    """
    if not isinstance(response, str):
        return None
    text = " ".join(response.split())
    if not text or len(text) > MAX_REWRITTEN_CHARS:
        return None
    if _neutralize_tags(text) != text:
        return None
    if any(marker in text for marker in _PROMPT_ECHO_MARKERS):
        return None
    if text == " ".join(original.split()):
        return None
    return text


async def contextualizer_node(state: AgentState) -> AgentState:
    history = state.get("history")
    # Kiểm kiểu tường minh: `history` do nơi gọi dựng, giá trị lạ không được làm node ném lỗi.
    if not history or not isinstance(history, list):
        return state

    query = state["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUESTION_CHARS:
        return state

    history_block = render_history(history[-MAX_HISTORY_TURNS:], max_chars=HISTORY_MAX_CHARS)
    if not history_block:
        # Có `history` nhưng không lượt nào hợp lệ (role lạ, content rỗng...) → như lượt đầu.
        return state

    user_content = f"{history_block}\n\n{wrap_untrusted('user_query', _neutralize_tags(query))}"
    try:
        llm = get_llm()
        response = await asyncio.wait_for(
            llm.chat(
                messages=[
                    {"role": "system", "content": CONTEXTUALIZE_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                max_tokens=MAX_TOKENS,
            ),
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # Chỉ log TÊN lớp lỗi: thông điệp lỗi của client LLM có thể kèm nội dung request
        # (câu hỏi, lịch sử — PII).
        logger.warning(
            "Contextualizer LLM call failed (%s) — falling back to original query",
            type(exc).__name__,
        )
        return state

    rewritten = _clean_rewritten(response, query)
    if rewritten is None:
        return state
    return {**state, "rewritten_query": rewritten}
