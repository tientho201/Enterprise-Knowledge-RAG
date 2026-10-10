"""Chot be mat cong khai cua app.ingestion.pipeline sau khi xoa code chet.

run_ingestion_pipeline (cung detect_doc_type, CONTENT_TYPE_MAP) tung ghi
Qdrant/Postgres/Neo4j KHONG co owner_id va dung chunk_id ngau nhien — ai goi lai se
pha co lap du lieu va tinh idempotent. Duong ingestion that la
app/workers/tasks/ingestion.py::ingest_document. Test nay chan viec them lai cac ten
do, dong thoi giu nguyen nhung thu con duoc dung (extract_text, ScannedPdfError)."""

import ast
from pathlib import Path

import pytest

from app.ingestion import pipeline
from app.models.document import DocumentType

_REMOVED_NAMES = ("run_ingestion_pipeline", "detect_doc_type", "CONTENT_TYPE_MAP")

# Module chi con trich van ban: khong duoc import lai tang ghi du lieu (DB session,
# repository, S3, Qdrant, Neo4j, embedder, chunker).
_FORBIDDEN_IMPORT_PREFIXES = (
    "sqlalchemy",
    "qdrant_client",
    "neo4j",
    "app.repositories",
    "app.storage",
    "app.rag",
    "app.ingestion",
    "app.models.chunk",
    "app.core.config",
)


@pytest.mark.parametrize("name", _REMOVED_NAMES)
def test_dead_ingestion_names_are_gone(name: str):
    assert not hasattr(pipeline, name)


def test_extraction_surface_is_kept():
    assert callable(pipeline.extract_text)
    assert issubclass(pipeline.ScannedPdfError, ValueError)
    assert isinstance(pipeline._SCANNED_PDF_MIN_CHARS_PER_PAGE, int)


def test_module_defines_only_extraction_symbols():
    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    assert defined == {"extract_text", "ScannedPdfError"}


def test_module_does_not_import_write_layers():
    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offending = [m for m in imported if m.startswith(_FORBIDDEN_IMPORT_PREFIXES)]
    assert offending == []


def test_extract_text_txt_still_works():
    assert pipeline.extract_text("xin chào".encode(), DocumentType.txt) == "xin chào"
