"""
Celery tasks — document ingestion pipeline.

Storage split:
  - Raw files  → AWS S3        (download khi cần xử lý, delete khi document bị xóa)
  - Metadata   → Supabase/PG   (document records, chunks, audit logs)
  - Vectors    → Qdrant Cloud  (dense embeddings)
  - Graph      → Neo4j         (knowledge graph, best-effort)

All tasks are idempotent and retry-safe.
"""

import asyncio
import logging
import uuid

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Cố định — KHÔNG đổi giá trị này, đổi sẽ khiến mọi chunk_id hiện có (Postgres/
# Qdrant/Neo4j) bị tính lại thành giá trị khác, mất khả năng MERGE/dedupe với dữ
# liệu đã ingest trước đó.
_CHUNK_ID_NAMESPACE = uuid.UUID("c9f9b8f0-6b1e-4b2a-9c7d-1a2b3c4d5e6f")


def _make_chunk_id(document_id: str, chunk_index: int) -> str:
    """
    Chunk id tất định từ (document_id, chunk_index) — không đổi qua các lần chạy/
    retry/reindex, để Qdrant upsert, Neo4j MERGE và Postgres primary key đều hội
    tụ về cùng một identity thay vì sinh bản ghi trùng.
    """
    return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, f"{document_id}:{chunk_index}"))


# ── Ingest ────────────────────────────────────────────────────────────────────


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
    Download raw file from S3 → extract text → chunk → embed → save to Qdrant + Supabase + Neo4j.

    Args:
        document_id:  UUID of the Document record in Supabase/PostgreSQL.
        storage_path: S3 object key (e.g. "uuid/filename.pdf").
    """
    logger.info("Starting ingestion: document_id=%s s3=%s", document_id, storage_path)
    try:
        from qdrant_client.models import (
            Distance,
            PayloadSchemaType,
            PointStruct,
            VectorParams,
        )
        from sqlalchemy import delete as sa_delete

        from app.core.config import settings
        from app.db.session import AsyncSessionLocal
        from app.ingestion.chunker import DocumentChunker
        from app.ingestion.embedder import get_embedder
        from app.ingestion.pipeline import extract_text
        from app.models.chunk import Chunk
        from app.models.document import DocumentStatus
        from app.rag.retriever import get_qdrant_client
        from app.repositories.document_repo import DocumentRepository
        from app.storage.s3_client import get_s3_client

        # 1. Download raw file from S3 (sync — we're in a Celery worker thread)
        s3 = get_s3_client()
        file_bytes = s3.download_file(storage_path)
        logger.debug("Downloaded %d bytes from S3: %s", len(file_bytes), storage_path)

        async def _run() -> None:
            async with AsyncSessionLocal() as db:
                doc_repo = DocumentRepository(db)

                # 2. Fetch metadata from Supabase
                doc = await doc_repo.get_by_id(document_id)
                if not doc:
                    raise ValueError(f"Document {document_id} not found in database")

                await doc_repo.update_status(document_id, DocumentStatus.processing)

                # 3. Extract text
                text = extract_text(file_bytes, doc.type)
                if not text.strip():
                    raise ValueError("No text could be extracted from the document")

                # 4. Chunk
                chunker = DocumentChunker()
                chunks = chunker.chunk(
                    text,
                    metadata={"document_id": document_id, "document_name": doc.name},
                )

                # 5. Embed via OpenAI API
                embedder = get_embedder()
                embeddings = embedder.embed([c.content for c in chunks])

                # 6. Ensure Qdrant collection exists
                qdrant = get_qdrant_client()
                existing = [c.name for c in qdrant.get_collections().collections]
                if settings.QDRANT_COLLECTION_NAME not in existing:
                    qdrant.create_collection(
                        collection_name=settings.QDRANT_COLLECTION_NAME,
                        vectors_config=VectorParams(
                            size=embedder.dimension, distance=Distance.COSINE
                        ),
                    )

                # 6b. Payload index cho các field dùng để FILTER khi truy hồi.
                # Qdrant (strict mode / Cloud) từ chối search có filter nếu field chưa
                # được index → retrieval trả 400 "Index required". owner_id = data
                # isolation, document_id = giới hạn theo tài liệu. Idempotent: gọi lại
                # khi index đã tồn tại là no-op an toàn.
                for field in ("owner_id", "document_id"):
                    try:
                        qdrant.create_payload_index(
                            collection_name=settings.QDRANT_COLLECTION_NAME,
                            field_name=field,
                            field_schema=PayloadSchemaType.KEYWORD,
                        )
                    except Exception as idx_exc:  # noqa: BLE001
                        logger.debug("Payload index %s: %s", field, idx_exc)

                # 7. Build Qdrant points + Supabase chunk records
                points: list[PointStruct] = []
                chunk_records: list[Chunk] = []

                for chunk, embedding in zip(chunks, embeddings):
                    chunk_id = _make_chunk_id(document_id, chunk.chunk_index)
                    points.append(
                        PointStruct(
                            id=chunk_id,
                            vector=embedding,
                            payload={
                                "document_id": document_id,
                                "document_name": doc.name,
                                "chunk_index": chunk.chunk_index,
                                "content": chunk.content,
                                # Data isolation: retriever filter theo owner_id ở /chat.
                                "owner_id": doc.owner_id,
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

                # 8. Upsert vectors to Qdrant Cloud theo BATCH.
                # Doc lớn -> hàng nghìn point; upsert 1 lần dễ "write operation timed out"
                # (nhất là Qdrant Cloud region xa). Chia nhỏ để mỗi request gọn & retry-safe.
                upsert_batch = 100
                for i in range(0, len(points), upsert_batch):
                    qdrant.upsert(
                        collection_name=settings.QDRANT_COLLECTION_NAME,
                        points=points[i : i + upsert_batch],
                        wait=True,
                    )

                # 9. Save chunk metadata to Supabase/PostgreSQL.
                # chunk_id giờ tất định (bước 7) nên trùng với chunk_id của lần
                # ingest trước (retry hoặc reindex) — xoá row cũ theo document_id
                # trước khi insert để tránh đụng primary key. Idempotent: nếu
                # chưa có row nào (lần ingest đầu tiên) thì đây là no-op.
                await db.execute(sa_delete(Chunk).where(Chunk.document_id == document_id))
                db.add_all(chunk_records)

                # 10. Index graph edges to Neo4j (best-effort — failure does not abort ingestion)
                try:
                    from app.ingestion.graph_indexer import ChunkRecord, index_chunks_to_graph
                    from app.rag.graph_client import get_neo4j_driver

                    graph_chunks = [
                        ChunkRecord(
                            chunk_id=str(p.id),
                            content=(p.payload or {})["content"],
                            chunk_index=(p.payload or {})["chunk_index"],
                        )
                        for p in points
                    ]
                    index_chunks_to_graph(
                        driver=get_neo4j_driver(),
                        document_id=document_id,
                        document_name=doc.name,
                        chunks=graph_chunks,
                        owner_id=doc.owner_id,
                    )
                    logger.debug(
                        "Neo4j indexed %d chunks for document %s", len(graph_chunks), document_id
                    )
                except Exception as graph_exc:  # noqa: BLE001
                    logger.warning(
                        "Neo4j indexing skipped for document %s: %s", document_id, graph_exc
                    )

                # 10b. Provision layer (citation graph): viện dẫn nội bộ (C1, phase 1)
                # + viện dẫn ngoại/placeholder + LLM fallback viện dẫn ngầm (C2 +
                # phase 2). Best-effort RIÊNG với bước 10: lỗi ở đây không được kéo
                # sập Chunk-graph đã chạy ổn ở trên.
                try:
                    from app.ingestion.citation_llm_fallback import (
                        classify_implicit_resolutions,
                        resolve_implicit_citations,
                    )
                    from app.ingestion.graph_indexer import (
                        ProvisionRecord,
                        index_document_placeholders_to_graph,
                        index_external_placeholders_to_graph,
                        index_legal_document_to_graph,
                        index_provisions_to_graph,
                    )
                    from app.ingestion.structural_parser import (
                        extract_citations,
                        extract_document_code,
                        extract_external_citations,
                        find_implicit_citation_sentences,
                        parse_provisions,
                    )
                    from app.llm.factory import get_llm
                    from app.rag.graph_client import get_neo4j_driver

                    provisions = parse_provisions(text)
                    if provisions:
                        document_code = extract_document_code(text) or f"internal:{document_id}"
                        citation_records = extract_citations(text, provisions)

                        # ── Phase 2: viện dẫn ngoại (C2) + fallback LLM cho viện dẫn
                        # ngầm. implicit_* được GỘP vào citation_records/
                        # external_citations TRƯỚC khi build citation_pairs bên dưới,
                        # để dùng lại nguyên luồng index_provisions_to_graph hiện có.
                        external_citations = extract_external_citations(
                            text, provisions, document_code
                        )

                        implicit_candidates = find_implicit_citation_sentences(
                            text, max_sentences=settings.IMPLICIT_CITATION_MAX_SENTENCES
                        )
                        implicit_unresolved: list[str] = []
                        if implicit_candidates:
                            resolutions = await resolve_implicit_citations(
                                get_llm(), [c.sentence for c in implicit_candidates]
                            )
                            (
                                implicit_internal,
                                implicit_external,
                                implicit_unresolved,
                            ) = classify_implicit_resolutions(
                                provisions=provisions,
                                own_document_code=document_code,
                                candidates=implicit_candidates,
                                resolutions=resolutions,
                            )
                            citation_records = citation_records + implicit_internal
                            external_citations = external_citations + implicit_external
                            logger.debug(
                                "LLM implicit-citation fallback: document %s — %d ứng viên, "
                                "%d resolve nội bộ, %d resolve ngoại, %d không resolve được",
                                document_id,
                                len(implicit_candidates),
                                len(implicit_internal),
                                len(implicit_external),
                                len(implicit_unresolved),
                            )

                        provision_records = [
                            ProvisionRecord(
                                dieu=p.key.dieu,
                                khoan=p.key.khoan,
                                diem=p.key.diem,
                                content=p.content,
                            )
                            for p in provisions
                        ]

                        # Map Provision <-> Chunk theo giao vùng ký tự [char_start, char_end).
                        chunk_links: list[tuple[tuple[int, int | None, str | None], str]] = []
                        for p in provisions:
                            for chunk in chunks:
                                if chunk.char_start is None:
                                    continue
                                c_start = chunk.char_start
                                c_end = c_start + len(chunk.content)
                                if c_start < p.char_end and c_end > p.char_start:
                                    chunk_links.append(
                                        (
                                            (p.key.dieu, p.key.khoan, p.key.diem),
                                            _make_chunk_id(document_id, chunk.chunk_index),
                                        )
                                    )

                        citation_pairs = [
                            (
                                (c.source.dieu, c.source.khoan, c.source.diem),
                                (c.target.dieu, c.target.khoan, c.target.diem),
                            )
                            for c in citation_records
                        ]

                        index_provisions_to_graph(
                            driver=get_neo4j_driver(),
                            owner_id=doc.owner_id,
                            document_code=document_code,
                            provisions=provision_records,
                            chunk_links=chunk_links,
                            citations=citation_pairs,
                        )
                        logger.debug(
                            "Neo4j indexed %d provisions, %d chunk-links, %d citations "
                            "for document %s (document_code=%s)",
                            len(provision_records),
                            len(chunk_links),
                            len(citation_pairs),
                            document_id,
                            document_code,
                        )

                        # Document-level node (phase 3) — điểm neo cấp văn bản cho
                        # chính văn bản đang ingest. Backfill tự nhiên: nếu văn bản
                        # khác đã viện dẫn tới document_code này trước (placeholder
                        # LegalDocument), MERGE hội tụ và lấp đầy tại đây. PHẢI chạy
                        # TRƯỚC index_document_placeholders_to_graph bên dưới (cạnh
                        # xuất phát từ chính LegalDocument này khi source_key=None
                        # cần node đã tồn tại để MATCH trúng).
                        index_legal_document_to_graph(
                            driver=get_neo4j_driver(),
                            owner_id=doc.owner_id,
                            document_code=document_code,
                            name=doc.name,
                        )

                        # Chỉ viện dẫn ngoại CÓ Điều cụ thể mới đủ để tạo placeholder
                        # Provision (xem structural_parser.extract_external_citations —
                        # dieu=None là giới hạn phase 2 đã chốt, không bịa Điều).
                        resolvable_external = [
                            (
                                (c.source.dieu, c.source.khoan, c.source.diem)
                                if c.source
                                else None,
                                c.document_code,
                                c.dieu,
                                c.khoan,
                                c.diem,
                            )
                            for c in external_citations
                            if c.dieu is not None
                        ]
                        # Viện dẫn ngoại CHỈ CÓ mã văn bản (dieu=None) — phase 2 bỏ
                        # hẳn nhóm này (75% dữ liệu thật); phase 3 dùng LegalDocument
                        # để không mất liên kết cấp văn bản (xem graph_indexer.py).
                        doc_level_only = [
                            (
                                (c.source.dieu, c.source.khoan, c.source.diem)
                                if c.source
                                else None,
                                c.document_code,
                            )
                            for c in external_citations
                            if c.dieu is None
                        ]

                        if resolvable_external:
                            index_external_placeholders_to_graph(
                                driver=get_neo4j_driver(),
                                owner_id=doc.owner_id,
                                own_document_code=document_code,
                                citations=resolvable_external,
                            )

                        if doc_level_only:
                            index_document_placeholders_to_graph(
                                driver=get_neo4j_driver(),
                                owner_id=doc.owner_id,
                                own_document_code=document_code,
                                citations=doc_level_only,
                            )

                        logger.debug(
                            "Neo4j external citations for document %s: %d placeholder-eligible, "
                            "%d chỉ có mã văn bản (LegalDocument, phase 3), "
                            "%d câu viện dẫn ngầm không resolve được",
                            document_id,
                            len(resolvable_external),
                            len(doc_level_only),
                            len(implicit_unresolved),
                        )
                    else:
                        logger.debug(
                            "No Provisions parsed for document %s (non-legal or no Điều found)",
                            document_id,
                        )
                except Exception as prov_exc:  # noqa: BLE001
                    logger.warning(
                        "Provision indexing skipped for document %s: %s", document_id, prov_exc
                    )

                # 11. Update document status in Supabase
                await doc_repo.update_status(document_id, DocumentStatus.indexed)
                await db.commit()

        asyncio.run(_run())
        logger.info("Ingestion complete: document_id=%s chunks=%s", document_id, "ok")
        return {"document_id": document_id, "status": "indexed"}

    except Exception as exc:
        logger.error("Ingestion failed: document_id=%s error=%s", document_id, exc)
        raise self.retry(exc=exc)


# ── Delete vectors (+ S3 file) ────────────────────────────────────────────────


@celery_app.task(
    name="app.workers.tasks.ingestion.delete_document_vectors",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def delete_document_vectors(self, document_id: str, storage_path: str | None = None) -> dict:
    """
    Delete all vectors and graph nodes for a document, then delete the raw file from S3.

    Args:
        document_id:  UUID of the document.
        storage_path: S3 object key. If provided, the raw file is also deleted from S3.
                      Pass None to skip S3 deletion (e.g. during reindex — file must be kept).
    """
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from app.core.config import settings
        from app.rag.retriever import get_qdrant_client

        # 1. Delete vectors from Qdrant Cloud
        qdrant = get_qdrant_client()
        qdrant.delete(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        logger.debug("Qdrant vectors deleted for document %s", document_id)

        # 2. Delete graph nodes from Neo4j (best-effort)
        try:
            from app.ingestion.graph_indexer import delete_document_from_graph
            from app.rag.graph_client import get_neo4j_driver

            delete_document_from_graph(get_neo4j_driver(), document_id)
            logger.debug("Neo4j nodes deleted for document %s", document_id)
        except Exception as graph_exc:  # noqa: BLE001
            logger.warning("Neo4j delete skipped for document %s: %s", document_id, graph_exc)

        # 3. Delete raw file from S3 (only when explicitly requested — not during reindex)
        if storage_path:
            from app.storage.s3_client import get_s3_client

            try:
                get_s3_client().delete_file(storage_path)
                logger.debug("S3 file deleted: %s", storage_path)
            except Exception as s3_exc:  # noqa: BLE001
                logger.warning("S3 delete failed for %s: %s", storage_path, s3_exc)

        return {"document_id": document_id, "status": "deleted"}

    except Exception as exc:
        raise self.retry(exc=exc)


# ── Reindex ───────────────────────────────────────────────────────────────────


@celery_app.task(
    name="app.workers.tasks.ingestion.reindex_document",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def reindex_document(self, document_id: str, storage_path: str) -> dict:
    """
    Full reindex: delete old vectors → re-download from S3 → re-ingest.
    Raw S3 file is preserved. Uses Celery chain to guarantee ordering.

    Args:
        document_id:  UUID of the document.
        storage_path: S3 object key — passed through so ingest doesn't need a DB lookup.
    """
    try:
        from celery import chain

        # chain() guarantees delete finishes BEFORE ingest starts (fixes race condition)
        chain(
            delete_document_vectors.si(document_id, storage_path=None),  # None = keep S3 file
            ingest_document.si(document_id, storage_path),
        ).apply_async()

        logger.info("Reindex queued for document %s (s3=%s)", document_id, storage_path)
        return {"document_id": document_id, "status": "reindex_queued"}

    except Exception as exc:
        raise self.retry(exc=exc)


# ── Chat attachments (ảnh gửi kèm chat — không phải document) ─────────────────


@celery_app.task(
    name="app.workers.tasks.ingestion.delete_chat_attachments",
    bind=True,
    max_retries=3,
    retry_backoff=True,
)
def delete_chat_attachments(self, storage_paths: list[str]) -> dict:
    """Xóa ảnh chat khỏi S3 SAU KHI record `message_attachments` đã xóa ở DB (cascade
    qua xóa hội thoại/tin nhắn — xem ChatService.delete_conversation). Tách khỏi
    ingest_document/delete_document_vectors vì ảnh chat không đụng Qdrant/Neo4j, chỉ
    dùng chung queue "ingestion" hiện có để không cần đổi lệnh chạy worker.

    Idempotent: file đã không tồn tại (S3 delete_objects trên key vắng mặt) không bị
    coi là lỗi — an toàn khi Celery tự retry.
    """
    if not storage_paths:
        return {"status": "noop"}
    try:
        from app.storage.s3_client import get_s3_client

        get_s3_client().delete_files(storage_paths)
        logger.debug("Chat attachments deleted from S3: %d files", len(storage_paths))
        return {"status": "deleted", "count": len(storage_paths)}
    except Exception as exc:
        raise self.retry(exc=exc)
