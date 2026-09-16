"""DLP tối thiểu — phát hiện dấu hiệu "bulk extraction": câu trả lời chứa nguyên văn
đoạn dài từ NHIỀU tài liệu khác nhau, khác với hành vi hỏi-đáp thông thường (dấu hiệu
user đang dùng /chat để "hút" toàn văn thư viện tài liệu thay vì hỏi 1 câu cụ thể).

KHÔNG chặn (block) — chỉ log cảnh báo + audit log (models/audit_log.py đã có sẵn hạ
tầng). Chặn cứng dễ false-positive: câu hỏi hợp lệ như "trích nguyên văn Điều 5" cũng
tạo overlap dài với 1 tài liệu — chỉ đáng ngờ khi overlap dài xảy ra ở NHIỀU tài liệu
cùng lúc trong 1 câu trả lời.
"""

from dataclasses import dataclass

from app.rag.retriever import RetrievedChunk

MIN_VERBATIM_CHARS = 200
MIN_DISTINCT_DOCUMENTS = 3


@dataclass
class DLPResult:
    flagged: bool
    matched_documents: int
    reason: str | None = None


def _has_verbatim_overlap(answer: str, content: str, min_len: int) -> bool:
    """True nếu `answer` chứa ít nhất 1 đoạn liên tiếp >= min_len ký tự trùng khớp
    với `content` — sliding window bước min_len//2 (đủ để bắt overlap thật, không cần
    khớp từng ký tự vì content mỗi chunk chỉ ~800 ký tự, số chunk tối đa RERANK_TOP_K)."""
    if len(content) < min_len:
        return False
    step = max(min_len // 2, 1)
    for start in range(0, len(content) - min_len + 1, step):
        if content[start : start + min_len] in answer:
            return True
    return False


def check_bulk_extraction(
    final_answer: str | None,
    chunks: list[RetrievedChunk],
    min_verbatim_chars: int = MIN_VERBATIM_CHARS,
    min_distinct_documents: int = MIN_DISTINCT_DOCUMENTS,
) -> DLPResult:
    if not final_answer or not chunks:
        return DLPResult(flagged=False, matched_documents=0)

    matched_doc_ids = {
        chunk.document_id
        for chunk in chunks
        if _has_verbatim_overlap(final_answer, chunk.content, min_verbatim_chars)
    }

    flagged = len(matched_doc_ids) >= min_distinct_documents
    reason = (
        f"Câu trả lời chứa đoạn nguyên văn >= {min_verbatim_chars} ký tự từ "
        f"{len(matched_doc_ids)} tài liệu khác nhau (ngưỡng cảnh báo: "
        f"{min_distinct_documents})"
        if flagged
        else None
    )
    return DLPResult(flagged=flagged, matched_documents=len(matched_doc_ids), reason=reason)
