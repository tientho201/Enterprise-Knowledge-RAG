"""
citation_llm_fallback.py — LLM fallback cho viện dẫn ngầm (phase 2).

resolve_implicit_citations() dùng LLM giả (FakeLLM, không gọi OpenAI thật) để test
điều kiện gọi (batch 1 call, [] -> không gọi, parse JSON hỏng -> fallback an toàn).
classify_implicit_resolutions() thuần logic, không cần LLM.
"""

import json
from collections.abc import AsyncIterator

import pytest

from app.ingestion.citation_llm_fallback import (
    ImplicitCitationResolution,
    _dieu_looks_like_misread_khoan,
    classify_implicit_resolutions,
    resolve_implicit_citations,
)
from app.ingestion.structural_parser import (
    ImplicitCitationCandidate,
    ParsedProvision,
    ProvisionKey,
)
from app.llm.base import BaseLLM


class FakeLLM(BaseLLM):
    """LLM giả — đếm số lần gọi chat() để verify batching, trả response cấu hình sẵn."""

    def __init__(self, response: str):
        self.response = response
        self.call_count = 0
        self.last_messages: list[dict] | None = None

    async def chat(
        self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        self.call_count += 1
        self.last_messages = messages
        return self.response

    def stream_chat(
        self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


# ── resolve_implicit_citations ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_implicit_citations_empty_input_does_not_call_llm():
    llm = FakeLLM(response="[]")
    result = await resolve_implicit_citations(llm, [])
    assert result == []
    assert llm.call_count == 0


@pytest.mark.asyncio
async def test_resolve_implicit_citations_batches_all_sentences_into_one_call():
    """3 câu nghi ngờ -> đúng 1 lần gọi LLM (không phải 1 call/câu) — yêu cầu chi
    phí cốt lõi của phase 2."""
    response = json.dumps(
        [
            {
                "index": 0,
                "is_citation": True,
                "document_code": None,
                "dieu": 5,
                "khoan": None,
                "diem": None,
            },
            {
                "index": 1,
                "is_citation": False,
                "document_code": None,
                "dieu": None,
                "khoan": None,
                "diem": None,
            },
            {
                "index": 2,
                "is_citation": True,
                "document_code": "88/2019/NĐ-CP",
                "dieu": 3,
                "khoan": 1,
                "diem": "a",
            },
        ]
    )
    llm = FakeLLM(response=response)
    sentences = ["câu 1", "câu 2", "câu 3"]

    result = await resolve_implicit_citations(llm, sentences)

    assert llm.call_count == 1
    assert len(result) == 3
    assert result[0] == ImplicitCitationResolution(True, None, 5, None, None)
    assert result[1] == ImplicitCitationResolution(False, None, None, None, None)
    assert result[2] == ImplicitCitationResolution(True, "88/2019/NĐ-CP", 3, 1, "a")


@pytest.mark.asyncio
async def test_resolve_implicit_citations_missing_index_defaults_to_unresolved():
    """LLM bỏ sót 1 index trong response -> câu đó fallback về is_citation=False
    (an toàn: không bịa hơn là bỏ sót)."""
    response = json.dumps(
        [
            {
                "index": 0,
                "is_citation": True,
                "document_code": None,
                "dieu": 1,
                "khoan": None,
                "diem": None,
            }
        ]
    )
    llm = FakeLLM(response=response)
    result = await resolve_implicit_citations(llm, ["câu 1", "câu 2"])

    assert len(result) == 2
    assert result[0].is_citation is True
    assert result[1] == ImplicitCitationResolution(False, None, None, None, None)


@pytest.mark.asyncio
async def test_resolve_implicit_citations_malformed_json_falls_back_safely():
    llm = FakeLLM(response="không phải JSON hợp lệ {{{")
    result = await resolve_implicit_citations(llm, ["câu 1", "câu 2"])

    assert result == [
        ImplicitCitationResolution(False, None, None, None, None),
        ImplicitCitationResolution(False, None, None, None, None),
    ]


@pytest.mark.asyncio
async def test_resolve_implicit_citations_strips_markdown_code_fence():
    response = (
        "```json\n"
        + json.dumps(
            [
                {
                    "index": 0,
                    "is_citation": True,
                    "document_code": None,
                    "dieu": 7,
                    "khoan": None,
                    "diem": None,
                }
            ]
        )
        + "\n```"
    )
    llm = FakeLLM(response=response)
    result = await resolve_implicit_citations(llm, ["câu 1"])
    assert result[0].dieu == 7


@pytest.mark.asyncio
async def test_resolve_implicit_citations_non_array_json_falls_back_safely():
    llm = FakeLLM(response=json.dumps({"not": "an array"}))
    result = await resolve_implicit_citations(llm, ["câu 1"])
    assert result == [ImplicitCitationResolution(False, None, None, None, None)]


class RaisingLLM(BaseLLM):
    """LLM giả raise lỗi ngay khi gọi chat() — mô phỏng lỗi API/network thật (vd
    OpenAI 500 InternalServerError bắt được lúc chạy thử trên văn bản thật)."""

    async def chat(
        self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        raise RuntimeError("simulated provider 500 error")

    def stream_chat(
        self, messages: list[dict], temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]:
        raise NotImplementedError

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_resolve_implicit_citations_llm_call_exception_falls_back_safely():
    """llm.chat() ném exception (lỗi API/network, KHÔNG phải JSON hỏng) -> vẫn phải
    trả về fallback an toàn, KHÔNG được để exception lan ra ngoài — nếu không, lỗi
    tạm thời của LLM sẽ kéo sập toàn bộ bước Provision layer (C1 + placeholder) ở
    ingestion.py cho cả document đó, dù lỗi chỉ liên quan tới tính năng fallback."""
    result = await resolve_implicit_citations(RaisingLLM(), ["câu 1", "câu 2"])
    assert result == [
        ImplicitCitationResolution(False, None, None, None, None),
        ImplicitCitationResolution(False, None, None, None, None),
    ]


# ── _dieu_looks_like_misread_khoan ────────────────────────────────────────────


def test_dieu_looks_like_misread_khoan_true_case_thật_phase_2():
    assert _dieu_looks_like_misread_khoan("theo khoản 16 Điều này", dieu=16) is True


def test_dieu_looks_like_misread_khoan_false_when_dieu_explicit():
    """ "khoản 5 Điều 5" — số trùng nhưng Điều 5 được nêu tường minh -> hợp lệ."""
    assert _dieu_looks_like_misread_khoan("theo khoản 5 Điều 5", dieu=5) is False


def test_dieu_looks_like_misread_khoan_false_when_number_not_a_khoan():
    assert _dieu_looks_like_misread_khoan("theo Điều 16 của văn bản", dieu=16) is False


def test_dieu_looks_like_misread_khoan_false_when_no_numbers_match():
    assert _dieu_looks_like_misread_khoan("theo quy định pháp luật hiện hành", dieu=3) is False


# ── classify_implicit_resolutions ─────────────────────────────────────────────

_PROVISIONS = [
    ParsedProvision(key=ProvisionKey(dieu=1), char_start=0, char_end=50, content="Điều 1..."),
    ParsedProvision(
        key=ProvisionKey(dieu=1, khoan=1), char_start=10, char_end=50, content="1. ..."
    ),
    ParsedProvision(key=ProvisionKey(dieu=5), char_start=50, char_end=100, content="Điều 5..."),
]


def _candidate(sentence: str, char_start: int) -> ImplicitCitationCandidate:
    return ImplicitCitationCandidate(sentence=sentence, char_start=char_start)


def test_classify_implicit_resolutions_internal_when_target_exists():
    candidates = [_candidate("theo khoản trên", char_start=20)]  # nằm trong Điều 1 Khoản 1
    resolutions = [ImplicitCitationResolution(True, None, 5, None, None)]  # trỏ Điều 5 (tồn tại)

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )

    assert len(internal) == 1
    assert internal[0].source == ProvisionKey(dieu=1, khoan=1)
    assert internal[0].target == ProvisionKey(dieu=5)
    assert external == []
    assert unresolved == []


def test_classify_implicit_resolutions_internal_target_not_found_is_unresolved():
    """Không bịa placeholder nội bộ — giữ đúng nguyên tắc đã chốt ở phase 1."""
    candidates = [_candidate("theo khoản trên", char_start=20)]
    resolutions = [ImplicitCitationResolution(True, None, 99, None, None)]  # Điều 99 không tồn tại

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )
    assert internal == []
    assert external == []
    assert unresolved == ["theo khoản trên"]


def test_classify_implicit_resolutions_external_when_document_code_differs():
    candidates = [_candidate("theo văn bản nêu trên", char_start=20)]
    resolutions = [ImplicitCitationResolution(True, "88/2019/NĐ-CP", 5, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )
    assert internal == []
    assert len(external) == 1
    assert external[0].document_code == "88/2019/NĐ-CP"
    assert external[0].dieu == 5
    assert external[0].source == ProvisionKey(dieu=1, khoan=1)
    assert unresolved == []


def test_classify_implicit_resolutions_not_a_citation_is_unresolved():
    candidates = [_candidate("câu bình thường", char_start=20)]
    resolutions = [ImplicitCitationResolution(False, None, None, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS, own_document_code=None, candidates=candidates, resolutions=resolutions
    )
    assert (internal, external, unresolved) == ([], [], ["câu bình thường"])


def test_classify_implicit_resolutions_missing_dieu_is_unresolved():
    """is_citation=true nhưng dieu=None (LLM không xác định được Điều cụ thể) ->
    không đủ để tạo cạnh/placeholder, chỉ ghi nhận unresolved."""
    candidates = [_candidate("theo pháp luật hiện hành", char_start=20)]
    resolutions = [ImplicitCitationResolution(True, None, None, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS, own_document_code=None, candidates=candidates, resolutions=resolutions
    )
    assert (internal, external) == ([], [])
    assert unresolved == ["theo pháp luật hiện hành"]


def test_classify_implicit_resolutions_source_outside_any_provision_is_unresolved():
    candidates = [_candidate("câu ở phần mở đầu", char_start=200)]  # ngoài mọi range
    resolutions = [ImplicitCitationResolution(True, None, 5, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS, own_document_code=None, candidates=candidates, resolutions=resolutions
    )
    assert (internal, external) == ([], [])
    assert unresolved == ["câu ở phần mở đầu"]


def test_classify_implicit_resolutions_self_reference_is_unresolved():
    """Nguồn == đích (LLM trỏ ngược lại chính Provision chứa câu đó) -> vô nghĩa,
    giống quy tắc self-reference của C1 (extract_citations)."""
    candidates = [_candidate("câu tự trỏ", char_start=0)]  # nằm trong Điều 1
    resolutions = [ImplicitCitationResolution(True, None, 1, None, None)]  # trỏ lại Điều 1

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS, own_document_code=None, candidates=candidates, resolutions=resolutions
    )
    assert (internal, external) == ([], [])
    assert unresolved == ["câu tự trỏ"]


def test_classify_implicit_resolutions_rejects_dieu_confused_with_khoan_number():
    """Case thật phase 2: câu "...khoản 16 Điều này" khiến LLM trả dieu=16 (nhầm
    số khoản thành số điều — "Điều này" không nêu số cụ thể). Phase 3: phải bị
    loại (unresolved), KHÔNG được tạo cạnh nội bộ."""
    candidates = [_candidate("theo khoản 16 Điều này", char_start=20)]  # trong Điều 1 Khoản 1
    resolutions = [ImplicitCitationResolution(True, None, 16, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )
    assert internal == []
    assert external == []
    assert unresolved == ["theo khoản 16 Điều này"]


def test_classify_implicit_resolutions_rejects_dieu_confused_with_khoan_number_external():
    """Cùng dấu hiệu hallucination nhưng ở nhánh external (document_code khác) —
    validation phải chạy TRƯỚC khi phân nhánh internal/external, không riêng gì
    internal."""
    candidates = [_candidate("theo khoản 16 văn bản nêu trên", char_start=20)]
    resolutions = [ImplicitCitationResolution(True, "88/2019/NĐ-CP", 16, None, None)]

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )
    assert internal == []
    assert external == []
    assert unresolved == ["theo khoản 16 văn bản nêu trên"]


def test_classify_implicit_resolutions_allows_same_number_for_dieu_and_khoan_when_explicit():
    """ "khoản 5 Điều 5" — cùng số 5 xuất hiện cạnh cả "khoản" lẫn "Điều" là HỢP LỆ
    (câu nêu tường minh "Điều 5"), không phải hallucination. Validation không được
    false-positive loại bỏ ca này."""
    candidates = [_candidate("theo khoản 5 Điều 5 của văn bản nêu trên", char_start=20)]
    resolutions = [ImplicitCitationResolution(True, None, 5, None, None)]  # trỏ Điều 5 (tồn tại)

    internal, external, unresolved = classify_implicit_resolutions(
        _PROVISIONS,
        own_document_code="99/2024/NĐ-CP",
        candidates=candidates,
        resolutions=resolutions,
    )
    assert len(internal) == 1
    assert internal[0].target == ProvisionKey(dieu=5)
    assert unresolved == []


def test_classify_implicit_resolutions_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        classify_implicit_resolutions(
            _PROVISIONS,
            own_document_code=None,
            candidates=[_candidate("a", 0)],
            resolutions=[],
        )
