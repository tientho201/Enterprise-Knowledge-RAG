"""PDF connector — wraps the ingestion pipeline for local PDF files."""

from pathlib import Path

from app.connectors.base import BaseConnector, ConnectorDocument
from app.ingestion.pipeline import extract_text
from app.models.document import DocumentType


class PDFConnector(BaseConnector):
    # Connectors intentionally have source-specific load signatures (PDF needs a file path).
    def load(self, file_path: str) -> list[ConnectorDocument]:  # type: ignore[override]
        path = Path(file_path)
        file_bytes = path.read_bytes()
        text = extract_text(file_bytes, DocumentType.pdf)
        return [
            ConnectorDocument(
                id=str(path.stem),
                title=path.name,
                content=text,
                source_url=str(path.absolute()),
                metadata={"file_size": len(file_bytes)},
            )
        ]

    def sync(self, **kwargs) -> dict:
        raise NotImplementedError("Use upload endpoint for PDF files")

    def diff(self, last_sync_ts: float, **kwargs) -> list[ConnectorDocument]:
        raise NotImplementedError("PDF connector does not support diff")
