"""Guardrail node: chặn cứng câu hỏi injection/jailbreak RÕ RÀNG trước khi vào router.

Rule-based (regex/keyword), KHÔNG gọi LLM — tiết kiệm chi phí/latency cho case rõ ràng.
Đây là lớp phòng thủ THỨ 2, đứng trước `prompt_defense.py` (lớp 1 — delimiter + câu
chống injection trong mọi system prompt). Guardrail này không thay thế lớp 1: câu injection
tinh vi hơn (không khớp regex) vẫn phải dựa vào lớp 1 để LLM tự chống.

Chỉ chặn pattern RÕ RÀNG (rủi ro false-positive thấp) — không chặn suy đoán mơ hồ, để
tránh chặn nhầm câu hỏi hợp lệ (vd người dùng hỏi về AI safety, prompt engineering...).
"""

import re

from app.agents.state import AgentState

BLOCKED_RESPONSE = (
    "Xin lỗi, tôi không thể thực hiện yêu cầu này. Tôi chỉ có thể trả lời câu hỏi dựa "
    "trên tài liệu nội bộ của hệ thống."
)

# Mỗi pattern match 1 dạng jailbreak/injection cụ thể — tiếng Anh + tiếng Việt.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(the\s+)?(above|previous|prior)\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?(the\s+)?(above|previous|prior)", re.I),
    re.compile(r"forget\s+(all\s+)?(the\s+)?(above|previous|prior)\s+instructions?", re.I),
    re.compile(
        r"(reveal|show|print|repeat|leak)\s+(your\s+|the\s+)?(full\s+|entire\s+)?"
        r"(system|developer)\s*prompt",
        re.I,
    ),
    re.compile(r"what\s+(is|are)\s+your\s+(system|developer)\s+prompt", re.I),
    re.compile(r"you\s+are\s+now\s+(in\s+)?(DAN|developer\s+mode|jailbroken)", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"act\s+as\s+if\s+you\s+have\s+no\s+(restrictions|rules|filters)", re.I),
    re.compile(
        r"(bỏ\s*qua|quên)\s+(mọi|tất\s*cả|các)?\s*(hướng\s*dẫn|chỉ\s*dẫn|lệnh|quy\s*tắc)"
        r"\s*(ở\s*trên|trước\s*đó|phía\s*trên)?",
        re.I,
    ),
    re.compile(
        r"(in|hiển\s*thị|tiết\s*lộ|nói)\s+(lại\s+)?(cho\s+tôi\s+)?(nguyên\s*văn\s+)?"
        r"system\s*prompt",
        re.I,
    ),
    re.compile(r"(bạn|mày)\s+(thực\s*ra|thật\s*ra)\s+là\s+(ai|gì)", re.I),
]


def is_injection_attempt(query: str) -> bool:
    """True nếu query khớp 1 pattern injection/jailbreak rõ ràng."""
    return any(p.search(query) for p in _INJECTION_PATTERNS)


async def guardrail_node(state: AgentState) -> AgentState:
    if is_injection_attempt(state["query"]):
        import logging

        logging.getLogger(__name__).warning(
            "Guardrail blocked potential injection/jailbreak attempt (owner_id=%s)",
            state.get("owner_id"),
        )
        return {**state, "intent": "blocked"}
    return state
