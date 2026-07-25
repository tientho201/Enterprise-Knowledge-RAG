"""
Structural parser cho văn bản luật: tách Điều / Khoản / Điểm thành các Provision
("địa chỉ pháp lý"), tách biệt hoàn toàn với DocumentChunker (chunker phục vụ
vector search — kích thước/overlap/nội dung chunk không đổi, xem chunker.py).

Ba loại regex phục vụ 3 việc khác nhau:
  - Header cấu trúc (_DIEU_HEADER/_KHOAN_HEADER/_DIEM_HEADER): tìm ranh giới
    Điều/Khoản/Điểm THẬT trong văn bản (vd "1." đầu dòng = khoản 1, KHÔNG phải
    cụm chữ "Khoản 1").
  - Câu viện dẫn NỘI BỘ (_CITATION_PATTERN, "C1"): tìm cụm "Điều 5", "khoản 2
    Điều 5"... xuất hiện BẤT KỲ ĐÂU trong nội dung, dùng để tạo cạnh VIEN_DAN
    trong CÙNG văn bản.
  - Câu viện dẫn NGOẠI (_EXTERNAL_CITATION_PATTERN/_STANDALONE_DOC_CODE_PATTERN,
    "C2"): tìm cụm trỏ tới VĂN BẢN KHÁC, có kèm mã văn bản (vd "Nghị định số
    88/2019/NĐ-CP") — dùng để tạo placeholder Provision (phase 2, xem
    graph_indexer.index_external_placeholders_to_graph).

Phase 1: chỉ viện dẫn NỘI BỘ. Viện dẫn trỏ tới (dieu, khoan, diem) không tồn tại
trong văn bản này bị bỏ qua (không tạo placeholder).

Phase 2 (bổ sung): viện dẫn NGOẠI (C2) + câu viện dẫn NGẦM (không match được C1/C2
bằng regex, cần LLM — xem app/ingestion/citation_llm_fallback.py). C2 tự nó KHÔNG
chuẩn hoá alias mã văn bản ("NĐ 88/2019" vs "Nghị định số 88/2019/NĐ-CP" ra 2 mã
khác nhau) — đây là giới hạn đã biết, để phase 3 xử lý dựa trên dữ liệu thật thu
được ở phase 2.

Ca biên: văn bản không có "Điều N" nào -> parse_provisions() trả về [] -> tầng
gọi (ingest_document) hiểu là non-legal, bỏ qua toàn bộ lớp Provision.
"""

import re
from dataclasses import dataclass

# ── Header cấu trúc (ranh giới Điều/Khoản/Điểm thật trong văn bản) ───────────
_DIEU_HEADER = re.compile(r"^[ \t]*[Đđ]iều\s+(\d+)\b", re.MULTILINE)
_KHOAN_HEADER = re.compile(r"^[ \t]*(\d+)\.\s", re.MULTILINE)
_DIEM_HEADER = re.compile(r"^[ \t]*([a-zđ])\)\s", re.MULTILINE)

# ── Câu viện dẫn (xuất hiện bất kỳ đâu trong nội dung) ────────────────────────
_CITATION_PATTERN = re.compile(
    r"(?:[Đđ]iểm\s+(?P<diem>[a-zđ])\s+)?"
    r"(?:[Kk]hoản\s+(?P<khoan>\d+)\s+)?"
    r"[Đđ]iều\s+(?P<dieu>\d+)"
)

# Mã văn bản của chính tài liệu đang ingest — chỉ tìm trong phần đầu văn bản
# (tiêu đề thường nêu ngay đầu), không quét toàn văn bản để tránh nhầm với
# mã văn bản NGOẠI được viện dẫn ở đâu đó bên trong (đó là việc của phase 2).
#
# Giữa từ loại văn bản và "số" cho phép tối đa 40 ký tự mô tả (KHÔNG xuống dòng,
# KHÔNG chứa chữ số) — phát hiện qua verify phase 3 trên văn bản hợp nhất thật
# (Luật Thương mại 36/2005/QH11, không có dòng "Số:"): tiêu đề luật thật thường có
# tên riêng chen giữa, vd "Luật Thương mại số 36/2005/QH11", "Luật Quản lý ngoại
# thương số 05/2017/QH14" — pattern cũ (không cho phép chen chữ) bỏ qua các match
# này (do "Thương mại"/"Quản lý ngoại thương" không khớp `\s*(?:số\s*)?`) và ăn
# nhầm mã của 1 văn bản khác được liệt kê ở "được sửa đổi, bổ sung bởi:" ngay sau
# đó (vd "Luật số 75/2025/QH15..."). Hậu tố `[A-ZĐ0-9\-]*` cho phép chữ số
# (khớp _DOC_TYPE_CODE) — thiếu chữ số khiến hậu tố "QH15" bị cắt cụt còn "QH".
_DOC_CODE_PATTERN = re.compile(
    r"(?:Nghị định|Thông tư|Luật|Quyết định|Nghị quyết)"
    r"\s*(?:[^\d\n]{0,40}?số)?\s*"
    r"(\d+/\d{4}(?:/[A-ZĐ][A-ZĐ0-9\-]*)?)"
)

# Dòng "Số:   15/2025/TT-BNV" ở phần thể thức công văn (letterhead) — cách văn bản
# luật THẬT tự khai báo số hiệu CHÍNH THỨC của CHÍNH nó. Ưu tiên hơn _DOC_CODE_PATTERN
# (xem extract_document_code) vì phần mở đầu văn bản luật thật rất hay có "Căn cứ
# Luật...; Căn cứ Nghị định số X...;" TRƯỚC dòng "Số:" — nếu chỉ dò
# _DOC_CODE_PATTERN (match ĐẦU TIÊN dạng "<loại văn bản> số <mã>") sẽ ăn nhầm mã của
# văn bản được viện dẫn trong "Căn cứ" thay vì mã của chính văn bản đang ingest.
_DOC_OWN_NUMBER_PATTERN = re.compile(r"Số\s*:\s*(\d+/\d{4}(?:/[A-ZĐ][A-ZĐ0-9\-]*)?)")

# ── C2: câu viện dẫn NGOẠI (trỏ tới văn bản khác, có kèm mã văn bản) ─────────
# Mã văn bản: "88/2019/NĐ-CP" (Nghị định/Thông tư/Quyết định/Nghị quyết, hậu tố
# chữ) hoặc "88/2019/QH14" (Luật, hậu tố chữ+số — "QH" + khoá Quốc hội) — hậu tố
# cho phép chữ số ([A-ZĐ0-9\-]*) để bắt được cả 2 dạng bằng 1 pattern.
_DOC_TYPE_CODE = (
    r"(?P<doc_type>Nghị định|Thông tư|Luật|Quyết định|Nghị quyết)\s*"
    r"(?:số\s*)?(?P<code>\d+/\d{4}(?:/[A-ZĐ][A-ZĐ0-9\-]*)?)"
)

# Ghép C1 + mã văn bản: "Điều 5 Nghị định số 88/2019/NĐ-CP", "khoản 2 Điều 5 của
# Thông tư 01/2024/TT-NHNN" -> resolve được xuống tận Provision (dieu cụ thể).
_EXTERNAL_CITATION_PATTERN = re.compile(
    r"(?:[Đđ]iểm\s+(?P<diem>[a-zđ])\s+)?"
    r"(?:[Kk]hoản\s+(?P<khoan>\d+)\s+)?"
    r"[Đđ]iều\s+(?P<dieu>\d+)\s+(?:của\s+)?" + _DOC_TYPE_CODE
)

# Chỉ có mã văn bản, không kèm Điều cụ thể: "theo Nghị định 88/2019/NĐ-CP".
# Giới hạn phase 2 đã chốt: KHÔNG bịa Điều -> chỉ liên kết được ở mức văn bản,
# không tạo được placeholder Provision (schema Provision luôn cần dieu). Xem
# extract_external_citations().
_STANDALONE_DOC_CODE_PATTERN = re.compile(_DOC_TYPE_CODE)

# ── Từ khoá gợi ý viện dẫn pháp lý NGẦM (câu không nêu số Điều/mã văn bản tường
# minh nhưng rõ ràng đang nói tới 1 quy định pháp luật cụ thể nào đó) — dùng để
# lọc ứng viên đưa cho LLM fallback (citation_llm_fallback.py), KHÔNG tự resolve
# bằng regex vì bản thân câu này không chứa đủ thông tin để resolve.
_IMPLICIT_CITATION_KEYWORDS = re.compile(
    r"quy định pháp luật hiện hành|quy định hiện hành|"
    r"văn bản nêu trên|văn bản đã nêu(?:\s+trên)?|"
    r"khoản trên|khoản nêu trên|điều trên|điều nêu trên|"
    r"pháp luật có liên quan|quy định có liên quan|quy định liên quan",
    re.IGNORECASE,
)

# Tách câu thô — đủ dùng để định vị char_start của câu nghi ngờ (không cần chính
# xác tuyệt đối về ngữ pháp, chỉ cần ranh giới hợp lý để map về Provision chứa nó).
_SENTENCE_SPLIT = re.compile(r"[^.!?\n]+[.!?]?")


@dataclass(frozen=True)
class ProvisionKey:
    """Định danh (dieu, khoan, diem) trong PHẠM VI 1 văn bản — chưa gồm owner/document_code."""

    dieu: int
    khoan: int | None = None
    diem: str | None = None


@dataclass
class ParsedProvision:
    key: ProvisionKey
    char_start: int
    char_end: int
    content: str


@dataclass
class ParsedCitation:
    source: ProvisionKey
    target: ProvisionKey


@dataclass
class ParsedExternalCitation:
    """
    Viện dẫn NGOẠI (C2) — trỏ tới văn bản khác *document_code* (khác chính văn bản
    đang ingest). source=None nếu vị trí viện dẫn không nằm trong Provision nào đã
    parse được (vd phần mở đầu văn bản).

    dieu=None nghĩa là câu chỉ nêu mã văn bản, không kèm Điều cụ thể — giới hạn
    phase 2 đã chốt: KHÔNG tạo placeholder Provision cho trường hợp này (không có
    dieu thì không có legal_address hợp lệ), chỉ dùng để thống kê/báo cáo.
    """

    source: ProvisionKey | None
    document_code: str
    dieu: int | None
    khoan: int | None = None
    diem: str | None = None


@dataclass
class ImplicitCitationCandidate:
    """Câu nghi ngờ viện dẫn pháp lý ngầm — ứng viên đưa cho LLM fallback."""

    sentence: str
    char_start: int


def _find_blocks(text: str, pattern: re.Pattern, block_end: int) -> list[tuple[str, int, int]]:
    """
    Trả về [(giá_trị_capture_group_1, char_start, char_end), ...] cho các match
    của *pattern* trong text[0:block_end], mỗi block kết thúc ở match kế tiếp
    (hoặc block_end nếu là match cuối).
    """
    matches = list(pattern.finditer(text, 0, block_end))
    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else block_end
        blocks.append((m.group(1), start, end))
    return blocks


def parse_provisions(text: str) -> list[ParsedProvision]:
    """
    Tách văn bản thành các Provision (Điều / Khoản trong Điều / Điểm trong Khoản).
    Trả về [] nếu không tìm thấy "Điều N" nào (văn bản không phải luật).
    """
    dieu_matches = list(_DIEU_HEADER.finditer(text))
    if not dieu_matches:
        return []

    provisions: list[ParsedProvision] = []

    for i, dieu_match in enumerate(dieu_matches):
        dieu_num = int(dieu_match.group(1))
        dieu_start = dieu_match.start()
        dieu_end = dieu_matches[i + 1].start() if i + 1 < len(dieu_matches) else len(text)

        provisions.append(
            ParsedProvision(
                key=ProvisionKey(dieu=dieu_num),
                char_start=dieu_start,
                char_end=dieu_end,
                content=text[dieu_start:dieu_end].strip(),
            )
        )

        for khoan_num_str, khoan_start, khoan_end in _find_blocks(text, _KHOAN_HEADER, dieu_end):
            if khoan_start < dieu_start:
                continue
            khoan_num = int(khoan_num_str)

            provisions.append(
                ParsedProvision(
                    key=ProvisionKey(dieu=dieu_num, khoan=khoan_num),
                    char_start=khoan_start,
                    char_end=khoan_end,
                    content=text[khoan_start:khoan_end].strip(),
                )
            )

            for diem_letter, diem_start, diem_end in _find_blocks(text, _DIEM_HEADER, khoan_end):
                if diem_start < khoan_start:
                    continue
                provisions.append(
                    ParsedProvision(
                        key=ProvisionKey(dieu=dieu_num, khoan=khoan_num, diem=diem_letter),
                        char_start=diem_start,
                        char_end=diem_end,
                        content=text[diem_start:diem_end].strip(),
                    )
                )

    return provisions


def containing_provision(pos: int, provisions: list[ParsedProvision]) -> ParsedProvision | None:
    """
    Provision hẹp nhất (theo độ dài range) chứa vị trí ký tự *pos*. Public — dùng
    lại bởi citation_llm_fallback.py để định vị nguồn (source) của câu viện dẫn
    ngầm sau khi LLM resolve.
    """
    candidates = [p for p in provisions if p.char_start <= pos < p.char_end]
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.char_end - p.char_start)


def extract_citations(text: str, provisions: list[ParsedProvision]) -> list[ParsedCitation]:
    """
    Tìm các câu viện dẫn nội bộ (_CITATION_PATTERN) trong toàn văn bản, resolve
    thành cạnh VIEN_DAN giữa 2 Provision đã parse được ở *provisions*.

    Bỏ qua (log-worthy nhưng không raise) nếu:
      - vị trí viện dẫn không nằm trong Provision nào (vd văn bản mở đầu trước
        Điều 1) -> không xác định được nguồn.
      - đích viện dẫn (dieu, khoan, diem) không tồn tại trong văn bản này ->
        phase 1 chưa làm placeholder, bỏ qua (phase 2 sẽ xử lý).
      - nguồn == đích (tự trỏ tới chính mình).
    """
    by_key = {p.key: p for p in provisions}
    citations: list[ParsedCitation] = []

    for m in _CITATION_PATTERN.finditer(text):
        dieu = int(m.group("dieu"))
        khoan = int(m.group("khoan")) if m.group("khoan") else None
        diem = m.group("diem") if m.group("diem") else None
        target_key = ProvisionKey(dieu=dieu, khoan=khoan, diem=diem)

        if target_key not in by_key:
            continue  # đích chưa tồn tại trong văn bản này — phase 2 (placeholder)

        source_provision = containing_provision(m.start(), provisions)
        if source_provision is None:
            continue  # viện dẫn nằm ngoài mọi Provision đã parse (vd phần mở đầu)

        if source_provision.key == target_key:
            continue  # tự trỏ tới chính mình — không có ý nghĩa với citation graph

        citations.append(ParsedCitation(source=source_provision.key, target=target_key))

    return citations


def extract_document_code(text: str, head_chars: int = 1000) -> str | None:
    """
    Suy ra "mã văn bản" của CHÍNH tài liệu đang ingest, từ ~head_chars ký tự đầu
    (tiêu đề văn bản luật thường nêu ngay đầu). None nếu không tìm thấy — caller
    tự quyết định fallback (vd f"internal:{document_id}").

    Ưu tiên _DOC_OWN_NUMBER_PATTERN (dòng "Số: <mã>" ở thể thức công văn) trước
    _DOC_CODE_PATTERN (dò "<loại văn bản> số <mã>" đầu tiên xuất hiện). Phát hiện
    qua verify phase 2 trên văn bản thật: Thông tư/Nghị định thật hầu như luôn mở
    đầu bằng "Căn cứ Luật...; Căn cứ Nghị định số X...;" TRƯỚC khi tới nội dung của
    chính nó — nếu chỉ dùng _DOC_CODE_PATTERN, match ĐẦU TIÊN trong head_chars rơi
    vào mã của văn bản ĐƯỢC VIỆN DẪN trong "Căn cứ", không phải mã của chính văn
    bản đang ingest.
    """
    own_number = _DOC_OWN_NUMBER_PATTERN.search(text[:head_chars])
    if own_number:
        return own_number.group(1)
    m = _DOC_CODE_PATTERN.search(text[:head_chars])
    return m.group(1) if m else None


def extract_external_citations(
    text: str,
    provisions: list[ParsedProvision],
    own_document_code: str | None,
) -> list[ParsedExternalCitation]:
    """
    C2: tìm câu viện dẫn tới VĂN BẢN KHÁC *own_document_code* (mã văn bản của
    chính tài liệu đang ingest — dùng để loại các chỗ văn bản tự nhắc lại mã của
    chính nó, vd "Nghị định này (số 99/2024/NĐ-CP)", không tính là ngoại).

    Trả về 2 dạng, phân biệt qua *dieu*:
      - dieu != None: "Điều 5 Nghị định số 88/2019/NĐ-CP" — đủ để tạo placeholder
        Provision (graph_indexer.index_external_placeholders_to_graph).
      - dieu == None: "theo Nghị định 88/2019/NĐ-CP" — chỉ có mã văn bản, KHÔNG
        bịa Điều. Giới hạn phase 2 đã chốt: caller chỉ dùng để thống kê/báo cáo,
        không tạo node Provision.

    Match của _EXTERNAL_CITATION_PATTERN (có Điều) được ưu tiên; span đã match bị
    loại khỏi lượt quét _STANDALONE_DOC_CODE_PATTERN để không đếm trùng 1 câu
    thành cả 2 dạng.
    """
    citations: list[ParsedExternalCitation] = []
    matched_spans: list[tuple[int, int]] = []

    for m in _EXTERNAL_CITATION_PATTERN.finditer(text):
        matched_spans.append((m.start(), m.end()))
        code = m.group("code")
        if own_document_code is not None and code == own_document_code:
            continue  # viện dẫn tới CHÍNH văn bản này bằng mã số -> không phải ngoại

        source_provision = containing_provision(m.start(), provisions)
        citations.append(
            ParsedExternalCitation(
                source=source_provision.key if source_provision else None,
                document_code=code,
                dieu=int(m.group("dieu")),
                khoan=int(m.group("khoan")) if m.group("khoan") else None,
                diem=m.group("diem") if m.group("diem") else None,
            )
        )

    for m in _STANDALONE_DOC_CODE_PATTERN.finditer(text):
        if any(start <= m.start() < end for start, end in matched_spans):
            continue  # đã tính ở nhánh có Điều cụ thể phía trên
        code = m.group("code")
        if own_document_code is not None and code == own_document_code:
            continue

        source_provision = containing_provision(m.start(), provisions)
        citations.append(
            ParsedExternalCitation(
                source=source_provision.key if source_provision else None,
                document_code=code,
                dieu=None,
                khoan=None,
                diem=None,
            )
        )

    return citations


def find_implicit_citation_sentences(
    text: str, max_sentences: int = 30
) -> list[ImplicitCitationCandidate]:
    """
    Tìm câu có từ khoá gợi ý viện dẫn pháp lý ngầm (_IMPLICIT_CITATION_KEYWORDS)
    nhưng KHÔNG match được C1 (_CITATION_PATTERN) hay C2
    (_EXTERNAL_CITATION_PATTERN / _STANDALONE_DOC_CODE_PATTERN) bằng regex — đây
    là tập ứng viên DUY NHẤT được đưa cho LLM
    (app/ingestion/citation_llm_fallback.py). KHÔNG chạy LLM cho toàn văn bản.

    max_sentences: trần cứng số câu/document — văn bản dài bất thường không được
    đội chi phí LLM không kiểm soát; câu vượt ngưỡng bị bỏ qua (KHÔNG raise, thứ
    tự ưu tiên là thứ tự xuất hiện trong văn bản).
    """
    candidates: list[ImplicitCitationCandidate] = []
    for m in _SENTENCE_SPLIT.finditer(text):
        raw = m.group()
        sentence = raw.strip()
        if not sentence:
            continue
        if not _IMPLICIT_CITATION_KEYWORDS.search(sentence):
            continue
        if _CITATION_PATTERN.search(sentence):
            continue  # đã match được C1 -> không phải "ngầm"
        if _EXTERNAL_CITATION_PATTERN.search(sentence) or _STANDALONE_DOC_CODE_PATTERN.search(
            sentence
        ):
            continue  # đã match được C2 -> không phải "ngầm"

        char_start = m.start() + raw.index(sentence)
        candidates.append(ImplicitCitationCandidate(sentence=sentence, char_start=char_start))
        if len(candidates) >= max_sentences:
            break

    return candidates
