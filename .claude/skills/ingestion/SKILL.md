---
name: ingestion
description: Dùng khi thiết kế, sửa, thêm bước, hoặc review ingestion pipeline OFFLINE của backend (parse, OCR, chunking, semantic refinement, metadata enrichment, dense/sparse embedding, index). Trigger khi user nhắc "ingestion pipeline", "chunking", "structural parser", "metadata enrichment", "sparse embedding", "BM25 index", "cải tiến pipeline nạp tài liệu", hoặc khi sửa file trong backend/app/ingestion/. Skill này định nghĩa pipeline OFFLINE MỤC TIÊU (target architecture) và map từng bước sang code thật hiện có — dùng để biết bước nào đã làm, bước nào còn thiếu, và nên thêm code ở đâu. Dùng cùng skill enterprise-knowledge-rag (context tổng quan) và rag-review (phần ONLINE — retrieval/rerank/generation/observability, nối tiếp ngay sau "Vector/Search DB" ở cuối skill này).
---

# Ingestion pipeline (OFFLINE) — target architecture vs. code thật

Đây là nửa OFFLINE của toàn bộ RAG pipeline (nửa ONLINE — query time — xem skill
`rag-review`). Pipeline mục tiêu (thứ tự bắt buộc, không đảo bước):

```
                    OFFLINE
┌──────────────────────────────────────────────┐
│  Documents                                   │
│      ↓                                       │
│  Parse / OCR / Structure                     │
│      ↓                                       │
│  Semantic Chunking + Metadata                │
│      ↓                                       │
│  ┌──────────────┬────────────────┐           │
│  ↓              ↓                │           │
│ Dense Embed   Sparse Embed       │           │
│  ↓              ↓                │           │
│ Vector Index   BM25 Index        │           │
│  └──────────────┴────────────────┘           │
│                 ↓                             │
│          Vector/Search DB                    │
└──────────────────────────────────────────────┘
```

"Semantic Chunking + Metadata" ở trên là 1 khối gộp — trong skill này tách thành 3 bước
con tường minh hơn để dễ trỏ vào code (**Structure-aware Recursive Chunking** →
**Semantic Refinement** → **Metadata Enrichment**), vì 3 việc này nằm ở 3 chỗ khác nhau
trong code thật và có gap khác nhau. Danh sách đầy đủ 8 bước:

```
DOCUMENT
   ↓
Parse + Structure (+ OCR)
   ↓
Structure-aware Recursive Chunking
   ↓
Semantic Refinement
   ↓
Metadata Enrichment
   ↓
Dense + Sparse Embedding
   ↓
Vector Index + BM25 Index → Vector/Search DB
```

Mỗi khi thêm/sửa code trong `backend/app/ingestion/`, xác định đang đụng vào bước nào ở
trên, đọc mục tương ứng dưới đây để biết code thật đang ở đâu, còn thiếu gì so với mục
tiêu, và không phá vỡ hợp đồng với bước liền sau. Bước cuối ("Vector/Search DB") là input
của nửa ONLINE (`rag-review`) — đổi schema payload/field ở đây phải kiểm tra luôn
`HybridRetriever`/`HybridScoreReranker` có đọc đúng field mới không.

## 0. DOCUMENT — nhận file

- Entry point: `POST /documents/upload` (`app/api/documents.py`) →
  `document_service.py` lưu S3 + tạo record `documents` (Postgres) → dispatch Celery task
  → `run_ingestion_pipeline()` (`app/ingestion/pipeline.py`) chạy toàn bộ các bước dưới.
- Upload không được block (ghi S3 + tạo DB record trong request, phần nặng chạy Celery).

## 1. Parse + Structure (+ OCR)

**Code thật, 2 lớp tách biệt — không gộp:**

- `pipeline.extract_text()` — parse thô theo `DocumentType` (pdf/docx/txt) → trả về
  1 chuỗi text phẳng, KHÔNG giữ cấu trúc. PDF hiện dùng `pypdf.PdfReader.extract_text()`
  — chỉ đọc được text layer sẵn có trong PDF, **không có OCR**: PDF scan (ảnh thuần,
  không có text layer) sẽ trả về chuỗi rỗng → `run_ingestion_pipeline()` raise
  `ValueError("No text could be extracted...")` và document rơi vào `DocumentStatus.failed`.
  Nếu cần OCR thật (Tesseract/Cloud Vision/textract), thêm nhánh xử lý trước khi gọi
  `pypdf` — nên detect "PDF không có text layer" (vd `extract_text()` trả rỗng/quá ngắn so
  với số trang) rồi fallback sang OCR, không OCR mọi PDF (tốn chi phí/latency không cần
  thiết cho PDF có text layer sẵn).
- `app/ingestion/structural_parser.py::parse_provisions()` — lớp "Structure" thật của
  pipeline mục tiêu: tách văn bản luật thành cây Điều → Khoản → Điểm
  (`ParsedProvision`, có `char_start`/`char_end`). Trả về `[]` nếu văn bản không có
  "Điều N" nào (non-legal doc) — caller phải xử lý case rỗng, không coi là lỗi.
- Cùng file còn có 2 lớp trích citation dùng ở bước Metadata Enrichment (không phải
  Parse): `extract_citations()` (nội bộ), `extract_external_citations()` (ngoại, cần
  `extract_document_code()`), và `find_implicit_citation_sentences()` (ứng viên cho LLM
  fallback ở `citation_llm_fallback.py`).

**Gap so với mục tiêu:** `parse_provisions()` chỉ chạy cho văn bản luật (regex
Điều/Khoản/Điểm tiếng Việt). Văn bản khác (policy doc thường, email, spec kỹ thuật...)
không có "Structure" nào — rơi thẳng vào chunking như plain text, mất hết heading/section
hierarchy. Nếu cần structure-aware cho non-legal doc, thêm parser mới theo Markdown
heading / DOCX style (`Heading 1/2/3`) / PDF font-size heuristic, cùng interface trả về
list block có `char_start`/`char_end` như `ParsedProvision` để bước 2 dùng lại được.

## 2. Structure-aware Recursive Chunking

**Code thật:** `app/ingestion/chunker.py::DocumentChunker` — `RecursiveCharacterTextSplitter`
(`chunk_size=800`, `chunk_overlap=200`, đọc từ `settings`, xem `enterprise-knowledge-rag`
skill). `add_start_index=True` để mỗi `TextChunk` có `char_start` — đây là điểm nối duy
nhất hiện có giữa chunking và structure.

**Gap so với mục tiêu — quan trọng nhất trong pipeline:** `DocumentChunker.chunk()` gọi
trên toàn văn bản, **không nhận `list[ParsedProvision]` làm split boundary**. Nghĩa là
`RecursiveCharacterTextSplitter` có thể cắt ngang giữa 1 Điều/Khoản dù `structural_parser`
đã biết chính xác ranh giới đó. Hai lớp (parse-structure và chunk) hiện chạy độc lập,
chỉ nối lại gián tiếp qua `char_start` khi cần map chunk → provision cho citation graph
(`graph_indexer.py`), KHÔNG dùng để chặn việc cắt ngang Điều/Khoản khi chunking.

Nếu triển khai "structure-aware" thật: sửa `DocumentChunker.chunk()` nhận thêm
`boundaries: list[tuple[int, int]]` (từ `parse_provisions()`), chunk riêng từng block
theo boundary trước, chỉ recursive-split nội bộ khi 1 block vượt `chunk_size` — không
cho splitter tự do đi ngang ranh giới Điều.

## 3. Semantic Refinement

**Chưa tồn tại trong code — bước còn thiếu hoàn toàn của pipeline hiện tại.** Sau khi có
chunk thô (bước 2), mục tiêu là refine trước khi enrich metadata:

- Merge chunk quá ngắn (vd chunk cuối 1 Điều chỉ còn vài từ do overlap cắt) vào chunk
  liền trước/sau.
- Dedup chunk trùng lặp gần như hoàn toàn (thường xảy ra ở overlap=200 lớn so với
  chunk_size=800 — 25% nội dung lặp giữa 2 chunk liên tiếp).
- Optional: LLM-based refinement (tóm tắt lại chunk quá dài về ngữ nghĩa, hoặc gắn 1 câu
  tóm tắt ngữ cảnh — "contextual retrieval" style) — cân nhắc kỹ vì tốn thêm 1 LLM
  call/chunk, xem cảnh báo về chi phí LLM tương tự `grader_node` trong skill `rag-review`.

Nếu thêm bước này, đặt file mới `app/ingestion/semantic_refiner.py`, gọi giữa
`chunker.chunk()` và bước embed trong `pipeline.py` — nhận `list[TextChunk]`, trả về
`list[TextChunk]` đã refine (giữ nguyên `chunk_index`/`char_start` hoặc tính lại nhất
quán, vì `graph_indexer.py` và bảng `chunks` phụ thuộc `chunk_index` để dựng cạnh
`NEXT_CHUNK`).

## 4. Metadata Enrichment

**Code thật — rải ở 3 nơi, chưa hợp nhất thành 1 bước rõ ràng:**

- `pipeline.py`: mỗi chunk có `document_id`, `document_name`, `chunk_index`, `content`
  (payload Qdrant) + `owner_id` (data isolation, xem `enterprise-knowledge-rag` skill) +
  `token_count`, `embedding_model` (bảng `chunks`).
- `structural_parser.py` + `citation_llm_fallback.py`: metadata pháp lý — Điều/Khoản/Điểm
  chứa chunk, cạnh viện dẫn nội bộ/ngoại — nhưng hiện áp vào **Neo4j graph node**
  (`graph_indexer.py`), KHÔNG áp vào **Qdrant payload**. Nghĩa là dense search (Qdrant)
  không filter/boost được theo "chunk này thuộc Điều 5" — chỉ graph traversal biết.
- `graph_indexer.py`: `_extract_article_numbers()` dùng regex riêng
  (`_ARTICLE_PATTERN`) trùng mục đích với `_CITATION_PATTERN` của `structural_parser.py`
  nhưng KHÔNG dùng lại — 2 regex song song cho cùng 1 việc là technical debt, nếu sửa 1
  bên nhớ kiểm tra bên còn lại.

**Gap:** nếu muốn "Metadata Enrichment" là 1 bước tường minh (đúng tinh thần pipeline
mục tiêu), nên gom lại: parse xong (bước 1) → chunk xong (bước 2/3) → 1 hàm
`enrich_metadata(chunks, provisions, citations) -> list[EnrichedChunk]` gắn `legal_address`
(dieu/khoan/diem), section title, citation list **vào payload Qdrant** luôn, không chỉ
Neo4j — để dense search cũng filter/boost được theo cấu trúc pháp lý.

## 5. Dense + Sparse Embedding

**Dense:** `app/ingestion/embedder.py::OpenAIEmbedder` — `text-embedding-3-small`
(1536 dims), batch qua `settings.EMBEDDING_BATCH_SIZE`. Đây là embedding DUY NHẤT hiện
có trong pipeline.

**Sparse: không tồn tại theo nghĩa cổ điển (BM25/TF-IDF vector).** Đây là quyết định
kiến trúc đã chốt của project — xem `enterprise-knowledge-rag` skill: leg "sparse" của
hybrid retrieval được THAY bằng Neo4j graph traversal (`NEXT_CHUNK`/`REFERENCES` edges,
weight 0.3) chứ không phải sparse vector thật. Nếu user/skill nào đề xuất thêm BM25/sparse
embedding thật (vd cho phù hợp đúng nghĩa "Dense + Sparse" của pipeline mục tiêu), đây là
thay đổi kiến trúc lớn — hỏi lại trước khi làm, không tự thêm `rank_bm25`/`FlagEmbedding`
lại vào `pyproject.toml` (đã bị dọn khỏi dependency để giảm ~2.5GB Docker image).

**Sync/async boundary:** `OpenAIEmbedder.embed()` gọi `openai.OpenAI` client sync — biết
là technical debt khi gọi từ async context (agent node), nhưng trong `pipeline.py` chạy
qua Celery task (sync context) nên OK, không cần wrap.

## 6. Vector Index + BM25 Index → Vector/Search DB

**2 index song song, không phải 1 — nhưng khác với diagram mục tiêu, index thứ 2 KHÔNG
phải BM25:**

- **Vector Index (Qdrant)** (`pipeline.py`): `PointStruct` — `id`, `vector` (dense
  embedding), `payload` (metadata bước 4). Collection tự tạo nếu chưa có
  (`VectorParams(size=embedder.dimension, distance=Distance.COSINE)`).
- **"BM25 Index" trong code thật là Neo4j graph, không phải BM25 thật**
  (`graph_indexer.py::index_chunks_to_graph`) — node `(:Chunk)` + cạnh
  `NEXT_CHUNK`/`REFERENCES`, best-effort (try/except bọc ngoài trong `pipeline.py`, lỗi
  Neo4j KHÔNG làm fail toàn bộ ingest — xem log warning). Đây là quyết định kiến trúc đã
  chốt (xem gap ở mục 5) — nếu cần BM25 index thật đúng nghĩa diagram (vd Qdrant sparse
  vectors hoặc Elasticsearch/OpenSearch riêng), đây là component mới hoàn toàn, không phải
  sửa Neo4j hiện có.

Khi thêm field mới ở bước Metadata Enrichment, phải quyết định field đó vào payload
Qdrant, property node Neo4j, hay cả hai — thiếu ở Qdrant thì retrieval dense không dùng
được field đó để filter (xem `HybridRetriever._build_qdrant_filter` trong
`app/rag/retriever.py`). Nửa ONLINE (skill `rag-review`) đọc trực tiếp từ 2 index này —
đổi tên field/collection ở đây phải đồng bộ sang đó.

## Checklist khi sửa/thêm 1 bước

- [ ] Xác định đang sửa bước nào trong 8 bước trên — không chunking rồi tự ý sửa luôn
  metadata enrichment trong cùng hàm nếu không cần thiết (giữ ranh giới rõ giữa các bước
  để dễ test độc lập).
- [ ] Không đổi `chunk_index` semantics nếu không rebuild lại `NEXT_CHUNK` edges trong
  Neo4j — `graph_indexer.py` dựa vào thứ tự `chunk_index` liên tục.
- [ ] Field mới trong metadata: cân nhắc thêm cả vào Qdrant payload (không chỉ Neo4j) —
  xem gap ở mục 4.
- [ ] Nếu đổi `chunk_size`/`chunk_overlap` hoặc thêm bước Semantic Refinement làm giảm
  overlap/dedup nội dung, kiểm tra lại `RERANK_TOP_K`/`DENSE_TOP_K` trong
  `app/core/config.py` vẫn hợp lý (số chunk giảm → có thể cần tăng top_k).
- [ ] Viết/update test ở `backend/app/tests/unit/test_chunker.py` (xem skill `testing`)
  khi đổi logic chunking hoặc thêm bước mới — pipeline test hiện tại (`test_ingestion.py`
  integration) chỉ test end-to-end, không cô lập được từng bước.
- [ ] Nếu phát hiện thêm gap mới không có trong skill này, cập nhật lại đúng mục tương
  ứng (0–6) — không tạo file mới liệt kê lại toàn bộ pipeline, tránh 2 nguồn chân lý lệch
  nhau.
