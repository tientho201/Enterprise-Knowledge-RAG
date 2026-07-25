"""
LLM fallback cho viện dẫn pháp lý NGẦM (implicit): câu có từ khoá gợi ý đang nói
tới 1 quy định pháp luật cụ thể nhưng KHÔNG match được C1 (nội bộ) hay C2 (ngoại,
mã văn bản tường minh) bằng regex — vd "theo quy định pháp luật hiện hành", "văn
bản nêu trên", "khoản trên". Xem structural_parser.find_implicit_citation_sentences
cho bước lọc ứng viên (từ khoá + loại trừ những gì regex đã bắt được).

Batch TOÀN BỘ câu nghi ngờ của 1 document vào 1 LLM call DUY NHẤT (không phải
1 call/câu) — chi phí không được tăng tuyến tính theo số câu nghi ngờ. Chạy 1 lần
lúc ingest (ingestion.py), KHÔNG chạy lúc query. Ngưỡng cắt số câu nghi ngờ/document
nằm ở find_implicit_citation_sentences(max_sentences=...), không phải ở module này.

Giới hạn đã biết (để phase 3 xử lý dựa trên dữ liệu thật): LLM có thể trả về
document_code/dieu không chính xác (hallucination) — chưa có bước xác thực chéo.
Để giảm rủi ro bịa số, prompt yêu cầu rõ: chỉ trích xuất khi số hiệu THỰC SỰ xuất
hiện trong câu; nếu không xác định được Điều cụ thể thì trả dieu=null (không đoán).
"""

import json
import logging
from dataclasses import dataclass

from app.ingestion.structural_parser import (
    ImplicitCitationCandidate,
    ParsedCitation,
    ParsedExternalCitation,
    ParsedProvision,
    ProvisionKey,
    containing_provision,
)
from app.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Bạn là trợ lý phân tích văn bản pháp luật tiếng Việt. Với mỗi câu
được đánh số dưới đây, xác định câu đó có đang viện dẫn tới MỘT quy định pháp luật cụ
thể hay không (Điều/Khoản/Điểm của một văn bản luật), dù câu không nêu rõ số hiệu
(vd "theo quy định pháp luật hiện hành", "văn bản nêu trên").

QUY TẮC BẮT BUỘC:
- CHỈ điền document_code/dieu/khoan/diem NẾU số hiệu đó THỰC SỰ xuất hiện tường minh
  trong chính câu đó. TUYỆT ĐỐI KHÔNG suy đoán hay bịa ra số Điều/mã văn bản.
- Nếu câu mơ hồ, không có cách nào xác định Điều cụ thể (vd chỉ nói "pháp luật hiện
  hành" chung chung), trả is_citation=true nhưng dieu=null.
- Nếu câu không thực sự viện dẫn gì cả (chỉ tình cờ chứa từ khoá), trả is_citation=false.

Trả về DUY NHẤT một JSON array, không kèm giải thích hay markdown code fence, đúng
schema sau cho MỌI câu được đánh số (không bỏ sót index nào):
[{"index": <int>, "is_citation": <bool>, "document_code": <string|null>,
  "dieu": <int|null>, "khoan": <int|null>, "diem": <string|null>}]
"""


@dataclass
class ImplicitCitationResolution:
    is_citation: bool
    document_code: str | None
    dieu: int | None
    khoan: int | None
    diem: str | None


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # bỏ dòng ```json hoặc ```
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


async def resolve_implicit_citations(
    llm: BaseLLM, sentences: list[str]
) -> list[ImplicitCitationResolution]:
    """
    1 LLM call cho TOÀN BỘ *sentences* (đã lọc + cắt ngưỡng bởi
    find_implicit_citation_sentences). [] đầu vào -> [] ra, không gọi LLM (tránh
    phí 1 call rỗng).

    Trả về đúng len(sentences) phần tử theo ĐÚNG thứ tự — index thiếu trong response
    của LLM (bỏ sót, JSON hỏng, ...) được điền is_citation=False (an toàn: không
    resolve nhầm hơn là bỏ sót một câu mơ hồ).
    """
    if not sentences:
        return []

    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": numbered},
    ]

    fallback = [
        ImplicitCitationResolution(
            is_citation=False, document_code=None, dieu=None, khoan=None, diem=None
        )
        for _ in sentences
    ]

    try:
        raw = await llm.chat(messages, temperature=0.0)
        parsed = json.loads(_strip_code_fence(raw))
        if not isinstance(parsed, list):
            raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    except Exception as exc:  # noqa: BLE001
        # Cố tình bắt RỘNG (không chỉ JSONDecodeError/ValueError) — llm.chat() có thể
        # raise lỗi API/network của provider (rate limit, 5xx, timeout...) tuỳ
        # implementation BaseLLM đang dùng (OpenAI SDK, vLLM client...). Đây CHỈ là
        # 1 fallback best-effort (viện dẫn ngầm) — 1 lỗi ở đây không được phép làm
        # sập toàn bộ bước Provision layer (C1 + placeholder) đang chạy trong cùng
        # try/except ở ingestion.py. Phát hiện qua chạy thật: OpenAI trả 500
        # (InternalServerError) không thuộc (JSONDecodeError, ValueError, TypeError)
        # nên trước đây lọt qua, kéo sập toàn bộ bước 10b cho document đó.
        logger.warning("LLM implicit-citation fallback: gọi/parse LLM thất bại: %s", exc)
        return fallback

    by_index = {
        item.get("index"): item
        for item in parsed
        if isinstance(item, dict) and isinstance(item.get("index"), int)
    }

    results = list(fallback)
    for i in range(len(sentences)):
        item = by_index.get(i)
        if item is None:
            continue
        dieu = item.get("dieu")
        doc_code = item.get("document_code")
        results[i] = ImplicitCitationResolution(
            is_citation=bool(item.get("is_citation", False)),
            document_code=doc_code if isinstance(doc_code, str) else None,
            dieu=int(dieu) if isinstance(dieu, int) else None,
            khoan=item.get("khoan") if isinstance(item.get("khoan"), int) else None,
            diem=item.get("diem") if isinstance(item.get("diem"), str) else None,
        )
    return results


def classify_implicit_resolutions(
    provisions: list[ParsedProvision],
    own_document_code: str | None,
    candidates: list[ImplicitCitationCandidate],
    resolutions: list[ImplicitCitationResolution],
) -> tuple[list[ParsedCitation], list[ParsedExternalCitation], list[str]]:
    """
    Ghép *candidates* (câu + vị trí, từ find_implicit_citation_sentences) với
    *resolutions* (LLM trả ra, resolve_implicit_citations — cùng thứ tự, cùng độ
    dài) và phân loại thành 3 nhóm để caller (ingestion.py) nối thẳng vào các danh
    sách citation đã có từ regex:

      - internal: document_code trùng own_document_code (hoặc null, nghĩa là LLM
        hiểu câu đang nói tới chính văn bản này) VÀ (dieu, khoan, diem) tồn tại
        THẬT trong *provisions* -> cạnh VIEN_DAN nội bộ (giống C1). Đích không tồn
        tại thật thì bỏ qua — giữ đúng nguyên tắc "không bịa placeholder nội bộ"
        đã chốt ở phase 1 (extract_citations).
      - external: document_code KHÁC own_document_code VÀ có dieu -> ứng viên
        placeholder (giống C2, nhánh có Điều cụ thể).
      - unresolved: is_citation=false, hoặc thiếu dieu, hoặc không định vị được
        Provision nguồn chứa câu đó -> không tạo gì, chỉ trả về câu gốc để log/báo
        cáo (phục vụ yêu cầu "câu viện dẫn ngầm nào LLM fallback bắt được/bỏ sót").

    len(candidates) phải bằng len(resolutions) — cùng đến từ 1 cặp gọi
    find_implicit_citation_sentences() / resolve_implicit_citations() không lọc gì
    thêm ở giữa; lệch độ dài là lỗi gọi sai của caller.
    """
    if len(candidates) != len(resolutions):
        raise ValueError(
            f"candidates ({len(candidates)}) và resolutions ({len(resolutions)}) "
            "phải cùng độ dài — xem docstring"
        )

    by_key = {p.key for p in provisions}
    internal: list[ParsedCitation] = []
    external: list[ParsedExternalCitation] = []
    unresolved: list[str] = []

    for candidate, res in zip(candidates, resolutions):
        if not res.is_citation or res.dieu is None:
            unresolved.append(candidate.sentence)
            continue

        source = containing_provision(candidate.char_start, provisions)
        if source is None:
            unresolved.append(candidate.sentence)
            continue

        document_code = res.document_code
        target_key = ProvisionKey(dieu=res.dieu, khoan=res.khoan, diem=res.diem)

        if document_code is None or document_code == own_document_code:
            if target_key not in by_key or source.key == target_key:
                unresolved.append(candidate.sentence)
                continue
            internal.append(ParsedCitation(source=source.key, target=target_key))
        else:
            external.append(
                ParsedExternalCitation(
                    source=source.key,
                    document_code=document_code,
                    dieu=res.dieu,
                    khoan=res.khoan,
                    diem=res.diem,
                )
            )

    return internal, external, unresolved
