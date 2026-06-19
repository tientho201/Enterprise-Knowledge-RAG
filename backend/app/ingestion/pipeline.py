"""
Ingestion pipeline:
Upload → Store (S3) → Extract text → Chunk → Embed → Save (Qdrant + DB + Neo4j)
"""
import io
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.chunker import DocumentChunker
from app.models.document import Document, DocumentStatus, DocumentType
from app.repositories.document_repo import DocumentRepository
from app.storage.s3_client import get_s3_client

CONTENT_TYPE_MAP = {
    "application/pdf": DocumentType.pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.docx,
    "text/plain": DocumentType.txt,
}


def detect_doc_type(filename: str, content_type: str) -> DocumentType:
    if content_type in CONTENT_TYPE_MAP:
        return CONTENT_TYPE_MAP[content_type]
    ext = filename.rsplit(".", 1)[-1].lower()
    mapping = {"pdf": DocumentType.pdf, "docx": DocumentType.docx, "txt": DocumentType.txt}
    return mapping.get(ext, DocumentType.txt)


def extract_text(file_bytes: bytes, doc_type: DocumentType) -> str:
    """Extract raw text from file bytes based on document type."""
    if doc_type == DocumentType.pdf:
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    elif doc_type == DocumentType.docx:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    elif doc_type == DocumentType.txt:
        return file_bytes.decode("utf-8", errors="replace")
    else:
        return file_bytes.decode("utf-8", errors="replace")


async def run_ingestion_pipeline(
    db: AsyncSession,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    source: str | None = None,
) -> Document:
    """
    Full ingestion pipeline — called by the Celery task after upload.
    Returns the Document record.
    """
    s3 = get_s3_client()
    doc_repo = DocumentRepository(db)
    chunker = DocumentChunker()

    doc_type = detect_doc_type(filename, content_type)
    object_name = f"{uuid.uuid4()}/{filename}"

    # Store raw file in S3
    s3.upload_bytes(object_name, file_bytes, content_type=content_type)

    # Create DB record
    doc = await doc_repo.create(
        name=filename,
        doc_type=doc_type,
        storage_path=object_name,
        source=source,
        file_size=len(file_bytes),
    )

    try:
        await doc_repo.update_status(doc.id, DocumentStatus.processing)

        # Extract text
        text = extract_text(file_bytes, doc_type)
        if not text.strip():
            raise ValueError("No text could be extracted from the document")

        # Chunk
        chunks = chunker.chunk(text, metadata={"document_id": doc.id, "document_name": filename})

        # Embed + save to Qdrant + DB
        from app.ingestion.embedder import get_embedder
        from app.rag.retriever import get_qdrant_client

        embedder = get_embedder()
        qdrant = get_qdrant_client()

        texts = [c.content for c in chunks]
        embeddings = embedder.embed(texts)

        # Ensure Qdrant collection exists
        from qdrant_client.models import Distance, VectorParams
        qdrant_collections = [c.name for c in qdrant.get_collections().collections]
        if settings.QDRANT_COLLECTION_NAME not in qdrant_collections:
            qdrant.create_collection(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                vectors_config=VectorParams(size=embedder.dimension, distance=Distance.COSINE),
            )

        from qdrant_client.models import PointStruct

        from app.models.chunk import Chunk

        points = []
        chunk_records = []

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=chunk_id,
                    vector=embedding,
                    payload={
                        "document_id": doc.id,
                        "document_name": filename,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                    },
                )
            )
            chunk_records.append(
                Chunk(
                    id=chunk_id,
                    document_id=doc.id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    token_count=chunk.token_count,
                    embedding_model=settings.EMBEDDING_MODEL,
                    qdrant_id=chunk_id,
                )
            )

        # Upsert to Qdrant
        qdrant.upsert(collection_name=settings.QDRANT_COLLECTION_NAME, points=points)

        # Save chunks to DB
        db.add_all(chunk_records)
        await db.flush()

        # Index into Neo4j knowledge graph (best-effort — failure does not abort ingestion)
        try:
            from app.ingestion.graph_indexer import ChunkRecord, index_chunks_to_graph
            from app.rag.graph_client import get_neo4j_driver

            graph_chunks = [
                ChunkRecord(
                    chunk_id=str(p.id),
                    content=p.payload["content"],
                    chunk_index=p.payload["chunk_index"],
                )
                for p in points
            ]
            index_chunks_to_graph(
                driver=get_neo4j_driver(),
                document_id=doc.id,
                document_name=filename,
                chunks=graph_chunks,
            )
        except Exception as graph_exc:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "Neo4j indexing skipped for document %s: %s", doc.id, graph_exc
            )

        await doc_repo.update_status(doc.id, DocumentStatus.indexed)

    except Exception as exc:
        await doc_repo.update_status(doc.id, DocumentStatus.failed, error_message=str(exc))
        raise

    return doc
