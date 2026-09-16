"""Detect PDF khong co text layer (scan thuan) — Task 6.1, xem
.claude/tasks/production-ops-gaps.md muc 6. Truoc day extract_text() tra chuoi
rong/qua ngan cho PDF scan, roi rai ValueError("No text could be extracted...")
chung chung o ingest_document — khong phan biet duoc voi loi khac (S3 loi,
pypdf loi doc file). Gio raise ScannedPdfError rieng, thong bao ro can OCR."""

import io
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfWriter

from app.ingestion.pipeline import ScannedPdfError, extract_text
from app.models.document import DocumentType


def _blank_pdf_bytes(num_pages: int) -> bytes:
    """PDF thuc, hop le, KHONG co text layer nao — dung pypdf.PdfWriter tao trang
    trong. extract_text() tren PDF nay phai tra chuoi rong."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_blank_pdf_raises_scanned_pdf_error():
    pdf_bytes = _blank_pdf_bytes(num_pages=3)
    with pytest.raises(ScannedPdfError, match="khong co text layer|text layer"):
        extract_text(pdf_bytes, DocumentType.pdf)


def test_scanned_pdf_error_message_mentions_ocr_and_page_count():
    pdf_bytes = _blank_pdf_bytes(num_pages=5)
    with pytest.raises(ScannedPdfError) as exc_info:
        extract_text(pdf_bytes, DocumentType.pdf)
    message = str(exc_info.value)
    assert "OCR" in message
    assert "5 trang" in message


def test_pdf_with_sufficient_text_does_not_raise():
    """Mock pypdf.PdfReader de gia lap PDF co text layer thuc (khong can tao PDF
    thuc voi noi dung van ban phuc tap qua pypdf.PdfWriter)."""
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "A" * 500  # >> nguong 20 ky tu/trang
    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]

    with patch("pypdf.PdfReader", return_value=fake_reader):
        text = extract_text(b"fake-pdf-bytes", DocumentType.pdf)

    assert text == "A" * 500


def test_pdf_just_below_threshold_raises():
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "x" * 10  # < nguong 20 ky tu/trang
    fake_reader = MagicMock()
    fake_reader.pages = [fake_page]

    with patch("pypdf.PdfReader", return_value=fake_reader):
        with pytest.raises(ScannedPdfError):
            extract_text(b"fake-pdf-bytes", DocumentType.pdf)


def test_scanned_pdf_error_is_a_value_error_subclass():
    """Khong pha vo code cu dang bat except ValueError xung quanh extract_text()."""
    assert issubclass(ScannedPdfError, ValueError)
