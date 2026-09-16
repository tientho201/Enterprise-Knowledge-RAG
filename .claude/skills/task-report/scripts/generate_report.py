"""
Render 1 task report (JSON) thành PDF + Markdown song song.

Chạy qua uv với dependency tạm thời (KHÔNG đụng backend/pyproject.toml hay
frontend/package.json — script này thuộc tooling của skill, không phải code sản phẩm):

    uv run --with fpdf2 python .claude/skills/task-report/scripts/generate_report.py \
        --input <path-to-report.json> --out-dir report

Input JSON schema — xem .claude/skills/task-report/scripts/report_schema.example.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from fpdf import FPDF

PAGE_MARGIN = 15
FONT = "Helvetica"

# True khi build_pdf() tìm được 1 font TTF Unicode hỗ trợ tiếng Việt trên máy và đã
# add_font() thành công — khi đó _latin1() KHÔNG được sanitize gì cả (font Unicode
# render được dấu trực tiếp). False → fallback core font Helvetica/Courier
# (Latin-1 only), _latin1() phải thật sự thay ký tự không encode được bằng '?'.
_using_unicode_font = False

# KHÔNG bundle font binary vào repo (tránh commit file .ttf nặng, không phải text) —
# chỉ dò các font Unicode phổ biến ĐÃ CÓ SẴN trên máy (Windows/Linux/macOS). Nếu máy
# không có font nào trong danh sách, PDF fallback về Helvetica không dấu — bản
# Markdown song song (build_markdown) luôn có dấu đầy đủ, không phụ thuộc font.
_UNICODE_FONT_CANDIDATES: list[tuple[str, str]] = [
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (r"C:\Windows\Fonts\tahoma.ttf", r"C:\Windows\Fonts\tahomabd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
     "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]


def _register_unicode_font(pdf: FPDF) -> str:
    """Dò + đăng ký 1 font Unicode có sẵn trên máy (ưu tiên Arial/DejaVu Sans — đều
    hỗ trợ đầy đủ tiếng Việt có dấu). Trả về tên font để dùng cho toàn bộ PDF; nếu
    không tìm thấy font nào, trả lại "Helvetica" (core font cũ, không dấu) và in
    cảnh báo ra stderr."""
    global _using_unicode_font
    for regular, bold in _UNICODE_FONT_CANDIDATES:
        if Path(regular).is_file():
            pdf.add_font("Unicode", "", regular)
            pdf.add_font("Unicode", "B", bold if Path(bold).is_file() else regular)
            pdf.add_font("Unicode", "I", regular)
            _using_unicode_font = True
            return "Unicode"
    print(
        "[generate_report] Khong tim thay font Unicode ho tro tieng Viet tren may nay "
        "(da thu Arial/Tahoma/DejaVu Sans/Liberation Sans/Noto Sans) - PDF se dung "
        "font Helvetica khong dau. Ban Markdown song song van co dau day du.",
        file=sys.stderr,
    )
    return FONT


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or "task"


def _latin1(text: str) -> str:
    """Khi có font Unicode (_using_unicode_font=True) — KHÔNG cần sanitize, trả
    nguyên văn để giữ dấu tiếng Việt. Khi fallback Helvetica (core font, chỉ có
    bảng mã Latin-1) — PHẢI thay ký tự không encode được bằng '?' để không crash
    fpdf2 (FPDFUnicodeEncodingException) khi multi_cell wrap dòng dài."""
    if _using_unicode_font:
        return text
    return text.encode("latin-1", "replace").decode("latin-1")


class ReportPDF(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FONT, "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, _latin1(f"Page {self.page_no()}"), align="C")


def _h1(pdf: ReportPDF, text: str) -> None:
    pdf.set_font(FONT, "B", 18)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 10, _latin1(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


def _meta_line(pdf: ReportPDF, label: str, value: str) -> None:
    # fpdf2 mac dinh multi_cell(width=0) di chuyen con tro X ve SAT LE PHAI trang (khong
    # phai le trai) sau khi ve xong — neu khong ep new_x="LMARGIN" thi lan goi cell() ke
    # tiep se cong don x vuot chieu rong trang va crash "Not enough horizontal space".
    pdf.set_font(FONT, "B", 10)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(35, 6, _latin1(label))
    pdf.set_font(FONT, "", 10)
    pdf.set_text_color(20, 20, 20)
    pdf.multi_cell(0, 6, _latin1(value), new_x="LMARGIN", new_y="NEXT")


def _h2(pdf: ReportPDF, text: str) -> None:
    pdf.ln(4)
    pdf.set_font(FONT, "B", 13)
    pdf.set_text_color(15, 60, 120)
    pdf.multi_cell(0, 8, _latin1(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    y = pdf.get_y()
    pdf.line(PAGE_MARGIN, y, pdf.w - PAGE_MARGIN, y)
    pdf.ln(2)


def _body(pdf: ReportPDF, text: str) -> None:
    pdf.set_font(FONT, "", 10.5)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 6, _latin1(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _bullet(pdf: ReportPDF, text: str) -> None:
    pdf.set_font(FONT, "", 10.5)
    pdf.set_text_color(30, 30, 30)
    x = pdf.get_x()
    pdf.cell(5, 6, _latin1("-"))
    pdf.set_x(x + 5)
    pdf.multi_cell(0, 6, _latin1(text), new_x="LMARGIN", new_y="NEXT")


def _code_block(pdf: ReportPDF, code: str) -> None:
    # "Courier" (core font) chỉ có Latin-1 — nếu đang dùng font Unicode (mục đích
    # chính là hiện dấu tiếng Việt), PHẢI dùng font đó ở đây luôn (mất tính monospace
    # nhưng tránh crash khi lệnh/mô tả có tiếng Việt), không được hardcode Courier.
    pdf.set_font(FONT if _using_unicode_font else "Courier", "", 9.5)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(20, 20, 20)
    x, y = pdf.get_x(), pdf.get_y()
    lines = code.strip("\n").split("\n") or [""]
    line_h = 5.5
    box_h = line_h * len(lines) + 4
    pdf.rect(x, y, pdf.w - 2 * PAGE_MARGIN, box_h, style="F")
    pdf.set_xy(x + 3, y + 2)
    for line in lines:
        pdf.multi_cell(pdf.w - 2 * PAGE_MARGIN - 6, line_h, _latin1(line))
        pdf.set_x(x + 3)
    pdf.set_xy(x, y + box_h + 2)


def _status_badge(pdf: ReportPDF, status: str) -> None:
    status_norm = status.strip().lower()
    colors = {
        "pass": (34, 139, 34),
        "fail": (178, 34, 34),
        "partial": (204, 140, 0),
    }
    r, g, b = colors.get(status_norm, (90, 90, 90))
    pdf.set_font(FONT, "B", 11)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 8, _latin1(f"Ket qua: {status.upper()}"))
    pdf.ln(8)
    pdf.set_text_color(30, 30, 30)


def build_pdf(data: dict[str, Any], out_path: Path) -> None:
    global FONT
    pdf = ReportPDF(format="A4")
    FONT = _register_unicode_font(pdf)
    pdf.set_auto_page_break(auto=True, margin=PAGE_MARGIN)
    pdf.set_margins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    pdf.add_page()

    _h1(pdf, data.get("task_title", "Task Report"))
    _meta_line(pdf, "Task ID:", str(data.get("task_id", "-")))
    _meta_line(pdf, "Ngay:", str(data.get("date", date.today().isoformat())))
    if data.get("source_task_file"):
        _meta_line(pdf, "Nguon task:", str(data["source_task_file"]))
    pdf.ln(3)

    if data.get("summary"):
        _h2(pdf, "1. Tom tat thay doi")
        _body(pdf, data["summary"])

    changed_files = data.get("changed_files") or []
    if changed_files:
        _h2(pdf, "2. File da sua")
        for item in changed_files:
            path = item.get("path", "") if isinstance(item, dict) else str(item)
            change = item.get("change", "") if isinstance(item, dict) else ""
            # ASCII "-" (không phải em-dash "—") — fpdf2 core font Latin-1 wrap dòng dài
            # qua nhiều dòng có thể gọi lại normalize_text trên đoạn chưa qua _latin1(),
            # crash FPDFUnicodeEncodingException dù _latin1() đã sanitize câu gốc.
            text = f"{path} - {change}" if change else path
            _bullet(pdf, text)

    test_steps = data.get("test_steps") or []
    if test_steps:
        _h2(pdf, "3. Huong dan test / verify")
        for idx, step in enumerate(test_steps, start=1):
            desc = step.get("step", "") if isinstance(step, dict) else str(step)
            command = step.get("command") if isinstance(step, dict) else None
            expected = step.get("expected") if isinstance(step, dict) else None
            _body(pdf, f"Buoc {idx}: {desc}")
            if command:
                _code_block(pdf, command)
            if expected:
                pdf.set_font(FONT, "I", 10)
                pdf.set_text_color(80, 80, 80)
                pdf.multi_cell(
                    0, 6, _latin1(f"Ky vong: {expected}"), new_x="LMARGIN", new_y="NEXT"
                )
                pdf.set_text_color(30, 30, 30)
                pdf.ln(1)

    result = data.get("result") or {}
    if result:
        _h2(pdf, "4. Ket qua")
        if result.get("status"):
            _status_badge(pdf, str(result["status"]))
        if result.get("notes"):
            _body(pdf, result["notes"])

    if data.get("rollback"):
        _h2(pdf, "5. Rollback neu can")
        _body(pdf, data["rollback"])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))


def build_markdown(data: dict[str, Any]) -> str:
    lines = [f"# {data.get('task_title', 'Task Report')}", ""]
    lines.append(f"- **Task ID:** {data.get('task_id', '-')}")
    lines.append(f"- **Ngày:** {data.get('date', date.today().isoformat())}")
    if data.get("source_task_file"):
        lines.append(f"- **Nguồn task:** {data['source_task_file']}")
    lines.append("")

    if data.get("summary"):
        lines += ["## 1. Tóm tắt thay đổi", "", data["summary"], ""]

    changed_files = data.get("changed_files") or []
    if changed_files:
        lines.append("## 2. File đã sửa")
        lines.append("")
        for item in changed_files:
            path = item.get("path", "") if isinstance(item, dict) else str(item)
            change = item.get("change", "") if isinstance(item, dict) else ""
            lines.append(f"- `{path}`" + (f" — {change}" if change else ""))
        lines.append("")

    test_steps = data.get("test_steps") or []
    if test_steps:
        lines.append("## 3. Hướng dẫn test / verify")
        lines.append("")
        for idx, step in enumerate(test_steps, start=1):
            desc = step.get("step", "") if isinstance(step, dict) else str(step)
            command = step.get("command") if isinstance(step, dict) else None
            expected = step.get("expected") if isinstance(step, dict) else None
            lines.append(f"{idx}. {desc}")
            if command:
                lines += ["", "   ```bash", f"   {command}", "   ```", ""]
            if expected:
                lines.append(f"   *Kỳ vọng:* {expected}")
                lines.append("")

    result = data.get("result") or {}
    if result:
        lines.append("## 4. Kết quả")
        lines.append("")
        if result.get("status"):
            lines.append(f"**Kết quả: {str(result['status']).upper()}**")
            lines.append("")
        if result.get("notes"):
            lines.append(result["notes"])
            lines.append("")

    if data.get("rollback"):
        lines += ["## 5. Rollback nếu cần", "", data["rollback"], ""]

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate task report PDF + Markdown")
    parser.add_argument("--input", required=True, help="Path to report JSON")
    parser.add_argument("--out-dir", default="report", help="Output directory (default: report)")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    date_str = str(data.get("date", date.today().isoformat()))
    slug = _slugify(f"{date_str}-{data.get('task_id', '')}-{data.get('task_title', 'task')}")

    out_dir = Path(args.out_dir)
    pdf_path = out_dir / f"{slug}.pdf"
    md_path = out_dir / f"{slug}.md"

    build_pdf(data, pdf_path)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(build_markdown(data), encoding="utf-8")

    print(f"PDF:      {pdf_path}")
    print(f"Markdown: {md_path}")


if __name__ == "__main__":
    main()
