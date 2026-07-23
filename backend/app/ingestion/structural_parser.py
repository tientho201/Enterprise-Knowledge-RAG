"""
Structural parser cho văn bản luật: tách Điều / Khoản / Điểm thành các Provision
("địa chỉ pháp lý"), tách biệt hoàn toàn với DocumentChunker (chunker phục vụ
vector search — kích thước/overlap/nội dung chunk không đổi, xem chunker.py).

Hai loại regex KHÔNG dùng chung, phục vụ 2 việc khác nhau:
  - Header cấu trúc (_DIEU_HEADER/_KHOAN_HEADER/_DIEM_HEADER): tìm ranh giới
    Điều/Khoản/Điểm THẬT trong văn bản (vd "1." đầu dòng = khoản 1, KHÔNG phải
    cụm chữ "Khoản 1").
  - Câu viện dẫn (_CITATION_PATTERN): tìm cụm "Điều 5", "khoản 2 Điều 5"... xuất
    hiện BẤT KỲ ĐÂU trong nội dung, dùng để tạo cạnh VIEN_DAN.

Phase 1: chỉ viện dẫn NỘI BỘ (trong cùng văn bản). Viện dẫn trỏ tới (dieu, khoan,
diem) không tồn tại trong văn bản này bị bỏ qua (không tạo placeholder — đó là
việc của phase 2).

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
_DOC_CODE_PATTERN = re.compile(
    r"(?:Nghị định|Thông tư|Luật|Quyết định|Nghị quyết)\s*(?:số\s*)?"
    r"(\d+/\d{4}(?:/[A-ZĐ][A-ZĐ\-]*)?)"
)


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


def _containing_provision(pos: int, provisions: list[ParsedProvision]) -> ParsedProvision | None:
    """Provision hẹp nhất (theo độ dài range) chứa vị trí ký tự *pos*."""
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

        source_provision = _containing_provision(m.start(), provisions)
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
    """
    m = _DOC_CODE_PATTERN.search(text[:head_chars])
    return m.group(1) if m else None
