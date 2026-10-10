"""Chọn LLM theo state cho các node của agent (BYOM passthrough) — hàm thuần, KHÔNG I/O.

Một điểm duy nhất để mọi node (router, grader, rewriter, contextualizer, generator) lấy
LLM theo cấu hình "Model tùy chỉnh" của người dùng thay vì mỗi node tự gọi `get_llm()`.
Uỷ thác NGUYÊN VẸN cho `llm/factory.py::get_llm_for_request` — cùng logic với
`agents/generator.py::_get_llm` — nên mọi quy tắc nằm ở factory, không lặp lại ở đây:

- Không có `api_key` (None / chuỗi rỗng / thiếu key trong state) → luôn `get_llm()` mặc
  định của server; `model` và `base_url` của người dùng bị BỎ QUA. Đây là ranh giới an
  toàn: khoá của server không bao giờ được gửi tới `base_url` do người dùng cung cấp.
- Có `api_key` → client OpenAI-compatible tạm thời cho request này (không cache).
  Thiếu `model` → model mặc định của server; thiếu `base_url` → endpoint mặc định của SDK.

Cố ý KHÔNG làm ở đây:

- Không log, không cache, không giữ `api_key` ở biến cấp module (không `lru_cache` theo khoá).
- Không bắt lỗi của factory: lỗi nổi thẳng lên. Rơi về `get_llm()` khi cấu hình BYOM hỏng
  sẽ âm thầm gửi dữ liệu của người dùng tới nhà cung cấp mặc định của server.
- Không chuẩn hoá/kiểm tra giá trị (strip, validate `base_url`): helper không được lỏng
  hơn hay chặt hơn factory, nếu không các node sẽ lệch với generator.

`AgentState` chỉ import khi type-check: module này không kéo `rag/retriever` lúc import
và không tạo import vòng với các node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.llm.base import BaseLLM
from app.llm.factory import get_llm_for_request

if TYPE_CHECKING:
    from app.agents.state import AgentState


def get_llm_for_state(state: AgentState) -> BaseLLM:
    """LLM cho request đang xử lý: model tùy chỉnh của người dùng nếu state có `api_key`,
    ngược lại LLM mặc định của server. Đọc bằng `.get()` nên state thiếu key vẫn hợp lệ.
    """
    return get_llm_for_request(
        model=state.get("model"),
        api_key=state.get("api_key"),
        base_url=state.get("base_url"),
    )
