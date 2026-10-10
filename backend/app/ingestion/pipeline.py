"""
Trích văn bản thô từ file tài liệu (PDF / DOCX / TXT) cho ingestion.

Module này CHỈ còn bước extract. Toàn bộ pipeline thật (S3 → chunk → embed →
Qdrant + Postgres + Neo4j, có `owner_id` và chunk_id tất định) nằm ở
`app/workers/tasks/ingestion.py::ingest_document`.
"""

import io

from app.models.document import DocumentType

# Ngưỡng heuristic: PDF scan thuần (ảnh, không có text layer) vẫn có thể trả về vài
# ký tự rác (watermark ẩn, metadata lẫn vào) nên KHÔNG dùng "rỗng tuyệt đối" — trung
# bình dưới ngưỡng này ký tự/trang coi như không có text layer thật. Chỉ 1 ngưỡng
# đơn giản, không phải OCR — mục đích là phân biệt lỗi "cần OCR" khỏi lỗi khác khi
# báo cho user, KHÔNG tự OCR (chưa hỗ trợ, xem Task 6.2 trong production-ops-gaps.md).
_SCANNED_PDF_MIN_CHARS_PER_PAGE = 20


class ScannedPdfError(ValueError):
    """PDF không có text layer (dạng scan/ảnh thuần) — cần OCR, hệ thống hiện CHƯA
    hỗ trợ OCR (xem Task 6.2). Subclass ValueError để không phá vỡ code cũ đang
    bắt `except ValueError`/`except Exception` xung quanh extract_text()."""


def extract_text(file_bytes: bytes, doc_type: DocumentType) -> str:
    """Extract raw text from file bytes based on document type."""
    if doc_type == DocumentType.pdf:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        page_texts = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(page_texts)

        num_pages = len(reader.pages) or 1
        avg_chars_per_page = len(text.strip()) / num_pages
        if avg_chars_per_page < _SCANNED_PDF_MIN_CHARS_PER_PAGE:
            raise ScannedPdfError(
                f"PDF không có text layer (dạng scan/ảnh) — chỉ trích được "
                f"{len(text.strip())} ký tự cho {num_pages} trang (trung bình "
                f"{avg_chars_per_page:.1f} ký tự/trang, ngưỡng tối thiểu "
                f"{_SCANNED_PDF_MIN_CHARS_PER_PAGE}). Hệ thống hiện CHƯA hỗ trợ OCR — "
                "vui lòng OCR tài liệu bằng công cụ bên ngoài trước khi tải lên."
            )
        return text
    elif doc_type == DocumentType.docx:
        import docx

        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif doc_type == DocumentType.txt:
        return file_bytes.decode("utf-8", errors="replace")
    else:
        return file_bytes.decode("utf-8", errors="replace")
