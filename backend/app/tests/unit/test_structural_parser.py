"""
structural_parser.py — tách Điều/Khoản/Điểm thành Provision + viện dẫn nội bộ (C1).

Sample text và các assertion được chuyển thẳng từ script chạy tay đã verify trên
Neo4j local (parse_provisions/extract_document_code/extract_citations khớp kết quả
đã in ra lúc verify runtime) — không đoán lại từ đầu.

Phase 2 (C2 — viện dẫn ngoại + câu viện dẫn ngầm) test ở cuối file, xem
test_extract_external_citations_* và test_find_implicit_citation_sentences_*.
"""

from app.ingestion.structural_parser import (
    ProvisionKey,
    extract_citations,
    extract_document_code,
    extract_external_citations,
    find_implicit_citation_sentences,
    parse_provisions,
)

SAMPLE_TEXT = """Nghị định số 99/2024/NĐ-CP quy định về bảo vệ dữ liệu cá nhân

Điều 1. Phạm vi điều chỉnh
1. Nghị định này quy định về bảo vệ dữ liệu cá nhân trong hoạt động xử lý dữ liệu.
2. Trường hợp vi phạm quy định tại khoản 1 Điều 5 của Nghị định này sẽ bị xử lý theo Điều 10.

Điều 5. Nguyên tắc xử lý dữ liệu
1. Dữ liệu cá nhân phải được xử lý theo quy định tại điểm a khoản 1 Điều 1.
2. Việc thu thập dữ liệu phải tuân thủ các nguyên tắc sau:
   a) Minh bạch và hợp pháp;
   b) Giới hạn theo mục đích quy định tại Điều 10.

Điều 10. Xử lý vi phạm
1. Tổ chức vi phạm Điều 5 sẽ bị xử phạt hành chính.
"""


def test_parse_provisions_three_levels():
    provisions = parse_provisions(SAMPLE_TEXT)
    keys = {p.key for p in provisions}

    assert ProvisionKey(dieu=1) in keys
    assert ProvisionKey(dieu=1, khoan=1) in keys
    assert ProvisionKey(dieu=1, khoan=2) in keys
    assert ProvisionKey(dieu=5) in keys
    assert ProvisionKey(dieu=5, khoan=1) in keys
    assert ProvisionKey(dieu=5, khoan=2) in keys
    assert ProvisionKey(dieu=5, khoan=2, diem="a") in keys
    assert ProvisionKey(dieu=5, khoan=2, diem="b") in keys
    assert ProvisionKey(dieu=10) in keys
    assert ProvisionKey(dieu=10, khoan=1) in keys
    assert len(provisions) == 10


def test_parse_provisions_char_offsets_match_original_text():
    """char_start/char_end phải khoanh đúng vùng văn bản gốc — đây là thứ dùng để
    map Provision <-> Chunk theo giao vùng ký tự, sai lệch ở đây kéo sai cả HAS_CHUNK."""
    provisions = parse_provisions(SAMPLE_TEXT)
    for p in provisions:
        assert SAMPLE_TEXT[p.char_start : p.char_end].strip() == p.content


def test_parse_provisions_diem_content_starts_with_own_marker():
    provisions = parse_provisions(SAMPLE_TEXT)
    by_key = {p.key: p for p in provisions}

    diem_a = by_key[ProvisionKey(dieu=5, khoan=2, diem="a")]
    assert diem_a.content.startswith("a) Minh bạch")

    diem_b = by_key[ProvisionKey(dieu=5, khoan=2, diem="b")]
    assert diem_b.content.startswith("b) Giới hạn")


def test_parse_provisions_non_legal_text_returns_empty_list():
    """Ca biên: văn bản không có 'Điều N' nào -> [] -> tầng gọi (ingestion.py) hiểu
    là non-legal, bỏ qua toàn bộ lớp Provision mà không lỗi."""
    text = "Đây là một đoạn văn bản bình thường, không phải văn bản luật."
    assert parse_provisions(text) == []


def test_extract_document_code_found_in_title():
    assert extract_document_code(SAMPLE_TEXT) == "99/2024/NĐ-CP"


def test_extract_document_code_not_found_returns_none():
    text = "Văn bản nội bộ không có mã số nào được nêu ở phần đầu."
    assert extract_document_code(text) is None


def test_extract_document_code_prefers_own_number_line_over_preamble_citation():
    """Phát hiện qua chạy phase 2 trên văn bản luật THẬT (Thông tư 15/2025/TT-BNV):
    phần mở đầu thể thức công văn luôn có 'Căn cứ Luật...; Căn cứ Nghị định số
    X...;' TRƯỚC dòng 'Số: <mã>' — nếu chỉ dò match ĐẦU TIÊN dạng '<loại văn bản>
    số <mã>' (_DOC_CODE_PATTERN) sẽ ăn nhầm mã của văn bản được viện dẫn trong
    'Căn cứ' thay vì mã CHÍNH THỨC của văn bản đang ingest."""
    text = (
        "BỘ NỘI VỤ\n"
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
        "Số:   15/2025/TT-BNV\n"
        "THÔNG TƯ\n"
        "Căn cứ Luật Thi đua, khen thưởng ngày 15 tháng 6 năm 2022;\n"
        "Căn cứ Nghị định số 152/2025/NĐ-CP ngày 14 tháng 6 năm 2025 của Chính phủ;\n"
        "Điều 1. Phạm vi điều chỉnh\n"
    )
    assert extract_document_code(text) == "15/2025/TT-BNV"


def test_extract_document_code_falls_back_to_narrative_form_when_no_so_line():
    """Không có dòng 'Số:' (vd văn bản không theo thể thức công văn chính thức) ->
    vẫn dùng _DOC_CODE_PATTERN như phase 1 — hành vi cũ không đổi."""
    text = "Nghị định số 99/2024/NĐ-CP quy định về bảo vệ dữ liệu cá nhân\n\nĐiều 1..."
    assert extract_document_code(text) == "99/2024/NĐ-CP"


def test_extract_document_code_handles_descriptive_words_between_type_and_so():
    """Phát hiện qua verify phase 3 trên văn bản hợp nhất thật (Luật Thương mại
    36/2005/QH11, không có dòng 'Số:'): tiêu đề có tên riêng chen giữa loại văn
    bản và "số" ("Luật THƯƠNG MẠI số..."), và văn bản khác được liệt kê ngay sau
    trong "được sửa đổi, bổ sung bởi:" khớp _DOC_CODE_PATTERN gọn hơn ("Luật số
    75/2025/QH15..." — không có tên chen giữa). Trước fix, match ĐẦU TIÊN rơi vào
    văn bản được liệt kê thay vì mã của chính văn bản đang ingest."""
    text = (
        "LUẬT\nTHƯƠNG MẠI\n\n"
        "Luật Thương mại số 36/2005/QH11 ngày 14 tháng 6 năm 2005 của Quốc hội, "
        "được sửa đổi, bổ sung bởi:\n"
        "1. Luật số 75/2025/QH15 ngày 16 tháng 6 năm 2025 của Quốc hội.\n\n"
        "Điều 1. Phạm vi điều chỉnh\n"
    )
    assert extract_document_code(text) == "36/2005/QH11"


def test_extract_document_code_suffix_with_trailing_digit_not_truncated():
    """Hậu tố mã văn bản có chữ số ở cuối (vd 'QH15', khoá Quốc hội) không được
    cắt cụt thành 'QH' — _DOC_CODE_PATTERN trước fix chỉ cho phép chữ cái trong
    phần lặp lại của hậu tố."""
    text = "Luật số 75/2025/QH15 ngày 16 tháng 6 năm 2025\n\nĐiều 1. Phạm vi điều chỉnh\n"
    assert extract_document_code(text) == "75/2025/QH15"


def test_extract_citations_resolves_internal_references():
    provisions = parse_provisions(SAMPLE_TEXT)
    citations = extract_citations(SAMPLE_TEXT, provisions)
    pairs = {(c.source, c.target) for c in citations}

    # Điều 1 Khoản 2: "...tại khoản 1 Điều 5..." và "...xử lý theo Điều 10."
    assert (ProvisionKey(dieu=1, khoan=2), ProvisionKey(dieu=5, khoan=1)) in pairs
    assert (ProvisionKey(dieu=1, khoan=2), ProvisionKey(dieu=10)) in pairs
    # Điều 5 Khoản 2 Điểm b: "...quy định tại Điều 10."
    assert (ProvisionKey(dieu=5, khoan=2, diem="b"), ProvisionKey(dieu=10)) in pairs
    # Điều 10 Khoản 1: "Tổ chức vi phạm Điều 5..."
    assert (ProvisionKey(dieu=10, khoan=1), ProvisionKey(dieu=5)) in pairs
    assert len(citations) == 4


def test_extract_citations_ignores_reference_to_nonexistent_target():
    """
    Điều 5 Khoản 1 viện dẫn "điểm a khoản 1 Điều 1" — điểm a KHÔNG tồn tại trong
    Khoản 1 Điều 1 của văn bản này (chỉ Điều 5 Khoản 2 có điểm a/b). Phase 1 không
    tạo placeholder cho đích không tồn tại trong văn bản -> câu viện dẫn này phải
    bị bỏ qua hoàn toàn, không xuất hiện trong kết quả. Đây chính là ca biên đã
    verify tay trên Neo4j local trước khi viết test này.
    """
    provisions = parse_provisions(SAMPLE_TEXT)
    citations = extract_citations(SAMPLE_TEXT, provisions)

    targets = {c.target for c in citations}
    assert ProvisionKey(dieu=1, khoan=1, diem="a") not in targets

    sources = {c.source for c in citations}
    assert ProvisionKey(dieu=5, khoan=1) not in sources


def test_extract_citations_ignores_self_reference():
    text = "Điều 1. Điều này (Điều 1) quy định phạm vi áp dụng.\n"
    provisions = parse_provisions(text)
    citations = extract_citations(text, provisions)
    assert citations == []


# ── Phase 2 — C2: viện dẫn ngoại ──────────────────────────────────────────────

EXTERNAL_SAMPLE_TEXT = """Điều 1. Phạm vi điều chỉnh
1. Việc xử lý vi phạm được thực hiện theo quy định tại Điều 5 Nghị định số 88/2019/NĐ-CP.
2. Ngoài ra, khoản 2 Điều 5 của Thông tư 01/2024/TT-NHNN cũng được áp dụng.

Điều 2. Áp dụng pháp luật
1. Trường hợp không có quy định riêng, áp dụng theo Luật số 88/2019/QH14.
2. Xem thêm Nghị định 88/2019/NĐ-CP để biết chi tiết.
"""


def test_extract_external_citations_resolves_dieu_plus_doc_code():
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, None)

    resolved = {(c.document_code, c.dieu, c.khoan, c.diem) for c in citations if c.dieu is not None}
    assert ("88/2019/NĐ-CP", 5, None, None) in resolved
    assert ("01/2024/TT-NHNN", 5, 2, None) in resolved


def test_extract_external_citations_doc_code_only_has_no_dieu():
    """'Nghị định 88/2019/NĐ-CP' không kèm Điều -> dieu=None, giới hạn phase 2 đã
    chốt (không bịa Điều), caller (ingestion.py) không tạo placeholder cho các
    citation này."""
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, None)

    doc_level_only = {c.document_code for c in citations if c.dieu is None}
    assert "88/2019/QH14" in doc_level_only
    assert "88/2019/NĐ-CP" in doc_level_only


def test_extract_external_citations_no_double_count_from_overlapping_patterns():
    """'Điều 5 Nghị định số 88/2019/NĐ-CP' phải được đếm 1 lần (nhánh có Điều), KHÔNG
    đếm thêm 1 lần nữa bởi _STANDALONE_DOC_CODE_PATTERN cho cùng đoạn text đó."""
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, None)
    assert len(citations) == 4


def test_extract_external_citations_excludes_own_document_code():
    """Viện dẫn tới CHÍNH mã văn bản đang ingest (own_document_code) không phải
    viện dẫn ngoại — phải bị loại, dù match được C2 pattern."""
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, "88/2019/NĐ-CP")

    codes = {c.document_code for c in citations}
    assert "88/2019/NĐ-CP" not in codes
    assert "01/2024/TT-NHNN" in codes
    assert "88/2019/QH14" in codes


def test_extract_external_citations_source_maps_to_containing_provision():
    provisions = parse_provisions(EXTERNAL_SAMPLE_TEXT)
    citations = extract_external_citations(EXTERNAL_SAMPLE_TEXT, provisions, None)

    by_code = {(c.document_code, c.dieu): c for c in citations}
    nd_citation = by_code[("88/2019/NĐ-CP", 5)]
    assert nd_citation.source == ProvisionKey(dieu=1, khoan=1)

    tt_citation = by_code[("01/2024/TT-NHNN", 5)]
    assert tt_citation.source == ProvisionKey(dieu=1, khoan=2)


# ── Phase 2 — câu viện dẫn ngầm (ứng viên cho LLM fallback) ──────────────────


def test_find_implicit_citation_sentences_matches_keyword_without_regex_hit():
    text = "Việc xử lý được thực hiện theo quy định pháp luật hiện hành."
    candidates = find_implicit_citation_sentences(text)
    assert len(candidates) == 1
    assert "quy định pháp luật hiện hành" in candidates[0].sentence


def test_find_implicit_citation_sentences_char_start_matches_original_text():
    text = "Đoạn mở đầu không liên quan.\nVí dụ như khoản trên đã quy định rõ.\n"
    candidates = find_implicit_citation_sentences(text)
    assert len(candidates) == 1
    c = candidates[0]
    assert text[c.char_start : c.char_start + len(c.sentence)] == c.sentence


def test_find_implicit_citation_sentences_excludes_sentence_already_matched_by_c1():
    """Câu vừa có từ khoá ngầm vừa có 'Điều N' tường minh -> đã match được C1, không
    phải 'ngầm' -> KHÔNG đưa vào tập ứng viên LLM (tránh gọi LLM cho câu regex đã
    resolve được)."""
    text = "Áp dụng theo quy định hiện hành tại Điều 5 của văn bản này."
    assert find_implicit_citation_sentences(text) == []


def test_find_implicit_citation_sentences_excludes_sentence_already_matched_by_c2():
    text = "Áp dụng theo quy định hiện hành tại Nghị định số 88/2019/NĐ-CP."
    assert find_implicit_citation_sentences(text) == []


def test_find_implicit_citation_sentences_no_keyword_returns_empty():
    text = "Đây là một câu hoàn toàn bình thường, không có từ khoá pháp lý nào."
    assert find_implicit_citation_sentences(text) == []


def test_find_implicit_citation_sentences_respects_max_sentences_cap():
    text = "".join(f"Câu số {i} theo khoản trên. " for i in range(50))
    candidates = find_implicit_citation_sentences(text, max_sentences=5)
    assert len(candidates) == 5
