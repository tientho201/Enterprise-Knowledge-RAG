"""Unit test cho DLP tối thiểu (app/agents/dlp.py) — Task 1.3, xem
.claude/tasks/production-ops-gaps.md mục 1."""

import pytest

from app.agents.dlp import check_bulk_extraction
from app.rag.retriever import RetrievedChunk


def _chunk(document_id: str, content: str, chunk_id: str = "c1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=f"doc-{document_id}",
        content=content,
        score=1.0,
        chunk_index=0,
    )


def test_no_flag_when_no_chunks():
    result = check_bulk_extraction("bất kỳ câu trả lời nào", [])
    assert result.flagged is False
    assert result.matched_documents == 0


def test_no_flag_when_answer_empty():
    chunks = [_chunk("d1", "x" * 500)]
    result = check_bulk_extraction("", chunks)
    assert result.flagged is False


def test_no_flag_for_normal_short_answer_with_paraphrase():
    chunks = [
        _chunk("d1", "Chính sách nghỉ phép quy định nhân viên được nghỉ 12 ngày mỗi năm."),
        _chunk("d2", "Quy trình xin nghỉ phép cần thông báo trước 3 ngày làm việc."),
    ]
    # Câu trả lời paraphrase, không copy nguyên văn dài từ chunk nào.
    answer = "Theo tài liệu, bạn được nghỉ 12 ngày/năm và cần báo trước vài ngày."
    result = check_bulk_extraction(answer, chunks, min_verbatim_chars=50)
    assert result.flagged is False


def test_flags_when_verbatim_overlap_from_many_documents():
    long_text_1 = "A" * 250
    long_text_2 = "B" * 250
    long_text_3 = "C" * 250
    chunks = [
        _chunk("d1", long_text_1),
        _chunk("d2", long_text_2),
        _chunk("d3", long_text_3),
    ]
    # Câu trả lời "nuốt" nguyên văn cả 3 chunk — dấu hiệu bulk extraction.
    answer = long_text_1 + "\n" + long_text_2 + "\n" + long_text_3
    result = check_bulk_extraction(answer, chunks, min_verbatim_chars=200, min_distinct_documents=3)
    assert result.flagged is True
    assert result.matched_documents == 3
    assert result.reason is not None


def test_does_not_flag_when_below_document_threshold():
    long_text_1 = "A" * 250
    long_text_2 = "B" * 250
    chunks = [_chunk("d1", long_text_1), _chunk("d2", long_text_2)]
    # Chỉ 2 tài liệu bị "copy nguyên văn" — dưới ngưỡng 3, không flag.
    answer = long_text_1 + "\n" + long_text_2
    result = check_bulk_extraction(answer, chunks, min_verbatim_chars=200, min_distinct_documents=3)
    assert result.flagged is False
    assert result.matched_documents == 2


@pytest.mark.asyncio
async def test_generator_node_sets_dlp_flag_on_bulk_extraction(monkeypatch):
    from app.agents import generator as generator_module

    long_text_1 = "A" * 250
    long_text_2 = "B" * 250
    long_text_3 = "C" * 250
    answer = long_text_1 + "\n" + long_text_2 + "\n" + long_text_3

    async def _fake_chat(*_args, **_kwargs):
        return answer

    class _FakeLLM:
        chat = staticmethod(_fake_chat)

    monkeypatch.setattr(generator_module, "_get_llm", lambda _state: _FakeLLM())

    state = {
        "query": "trích nguyên văn 3 tài liệu",
        "intent": "rag",
        "reranked_results": [
            _chunk("d1", long_text_1),
            _chunk("d2", long_text_2),
            _chunk("d3", long_text_3),
        ],
        "image_data_urls": None,
        "system_prompt": None,
        "search_tool": False,
    }
    result = await generator_module.generator_node(state)  # type: ignore[arg-type]
    assert result["dlp_flag"] is True
    assert result["dlp_reason"] is not None
