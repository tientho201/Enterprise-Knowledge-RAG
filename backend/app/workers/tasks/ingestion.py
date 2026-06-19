"""
Celery tasks for document ingestion pipeline.
All tasks are idempotent and retry-safe.
"""
import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.ingestion.ingest_document",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def ingest_document(self, document_id: str, storage_path: str) -> dict:
    """
    Extract, chunk, embed and index a document.
    Idempotent: safe to retry on failure.
    """
    logger.info("Starting ingestion for document %s", document_id)
    try:
        import uuid

        from qdrant_client.models import Distance, PointStruct, VectorParams

        from app.core.config import settings
        from app.db.session import AsyncSessionLocal
        from app.ingestion.chunker import DocumentChunker
        from app.ingestion.embedder import get_embedder
        from app.models.chunk import Chunk
        from app.models.document import DocumentStatus
        from app.rag.retriever import get_qdrant_client
        from app.repositories.document_repo import DocumentRepository
        from app.storage.s3_client import get_s3_client

        s3 = get_s3_client()
        file_bytes = s3.download_file(storage_path)

        async def _run():
            async with AsyncSessionLocal() as db:
                doc_repo = DocumentRepository(db)
                doc = await doc_repo.get_by_id(document_id)
                if not doc:
                    raise ValueError(f"Document {document_id} not found")

                await doc_repo.update_status(document_id, DocumentStatus.processing)

                from app.ingestion.pipeline import extract_text
                doc_type = doc.type
                text = extract_text(file_bytes, doc_type)

                chunker = DocumentChunker()
                chunks = chunker.chunk(text, metadata={"document_id": document_id})

                embedder = get_embedder()
                texts = [c.content for c in chunks]
                embeddings = embedder.embed(texts)

                qdrant = get_qdrant_client()
                collections = [c.name for c in qdrant.get_collections().collections]
                if settings.QDRANT_COLLECTION_NAME not in collections:
                    qdrant.create_collection(
                        collection_name=settings.QDRANT_COLLECTION_NAME,
                        vectors_config=VectorParams(size=embedder.dimension, distance=Distance.COSINE),
                    )

                points = []
                chunk_records = []
                for chunk, embedding in zip(chunks, embeddings):
                    chunk_id = str(uuid.uuid4())
                    points.append(
                        PointStruct(
                            id=chunk_id,
                            vector=embedding,
                            payload={
                                "document_id": document_id,
                                "document_name": doc.name,
                                "chunk_index": chunk.chunk_index,
                                "content": chunk.content,
                            },
                        )
                    )
                    chunk_records.append(
                        Chunk(
                            id=chunk_id,
                            document_id=document_id,
                            content=chunk.content,
                            chunk_index=chunk.chunk_index,
                            token_count=chunk.token_count,
                            embedding_model=settings.EMBEDDING_MODEL,
                            qdrant_id=chunk_id,
                        )
                    )

                qdrant.upsert(collection_name=settings.QDRANT_COLLECTION_NAME, points=points)
                db.add_all(chunk_records)

                # Index into Neo4j knowledge graph (best-effort)
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
                        document_id=document_id,
                        document_name=doc.name,
                        chunks=graph_chunks,
                    )
                except Exception as graph_exc:  # noqa: BLE001
                    logger.warning(
                        "Neo4j indexing skipped for document %s: %s", document_id, graph_exc
                    )

                await doc_repo.update_status(document_id, DocumentStatus.indexed)
                await db.commit()

        asyncio.run(_run())
        logger.info("Ingestion complete for document %s", document_id)
        return {"document_id": document_id, "status": "indexed"}

    except Exception as exc:
        logger.error("Ingestion failed for document %s: %s", document_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    name="app.workers.tasks.ingestion.delete_document_vectors",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def delete_document_vectors(self, document_id: str) -> dict:
    """Remove all vectors (Qdrant) and graph nodes (Neo4j) for a document."""
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from app.core.config import settings
        from app.rag.retriever import get_qdrant_client

        # Delete from Qdrant
        qdrant = get_qdrant_client()
        qdrant.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )

        # Delete from Neo4j (best-effort)
        try:
            from app.ingestion.graph_indexer import delete_document_from_graph
            from app.rag.graph_client import get_neo4j_driver

            delete_document_from_graph(get_neo4j_driver(), document_id)
        except Exception as graph_exc:  # noqa: BLE001
            logger.warning(
                "Neo4j delete skipped for document %s: %s", document_id, graph_exc
            )

        return {"document_id": document_id, "status": "vectors_deleted"}
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(
    name="app.workers.tasks.ingestion.reindex_document",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def reindex_document(self, document_id: str) -> dict:
    """Delete old vectors and re-ingest the document."""
    delete_document_vectors.delay(document_id)
    # Fetch storage_path from DB and re-run ingest
    async def _get_path():
        from app.db.session import AsyncSessionLocal
        from app.repositories.document_repo import DocumentRepository
        async with AsyncSessionLocal() as db:
            repo = DocumentRepository(db)
            doc = await repo.get_by_id(document_id)
            return doc.storage_path if doc else None

    storage_path = asyncio.run(_get_path())
    if storage_path:
        ingest_document.delay(document_id, storage_path)
    return {"document_id": document_id, "status": "reindex_queued"}
