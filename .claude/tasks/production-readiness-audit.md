# Production Readiness Audit

Cập nhật lần cuối: 2026-07-16 (session 3 — hardening bảo mật: data isolation RAG retrieval)

Nguồn chân lý kiến trúc: `.claude/skills/enterprise-knowledge-rag/SKILL.md`.
Checklist gốc viết từ snapshot cũ — mọi mục dưới đây đã được **verify lại bằng code thật**,
không tin mù checklist.

---

## Đã Obsolete (không cần fix — refactor cũ đã giải quyết)

- [x] **MinIO credentials mặc định** — MinIO đã bị loại khỏi project, thay bằng AWS S3.
  `grep -i minio backend/` chỉ còn khớp trong `backend/README.md` và `backend/CLAUDE.md`
  (docs stale), KHÔNG còn trong code. Không có credential MinIO nào để lo.
- [x] **Tách Dockerfile thành 2 target api/worker** — `docker-compose.prod.yml` dùng 1 image
  chung, chạy 3 service (api/worker/beat) qua `command:` override khác nhau. api/worker/beat
  cùng dependency set → multi-stage Dockerfile không mang lại lợi ích. Cách hiện tại đủ tốt.
- [x] **MinIO persistent volume/backup** — MinIO đã xóa. Verify thay thế: Redis ĐÃ có volume
  (`redis_data:/data`) + `--appendonly yes` trong `docker-compose.prod.yml`. OK.
- [x] **BGE-M3 CPU chậm** — BGE-M3 đã xóa hoàn toàn, giờ dùng OpenAI `text-embedding-3-small`
  qua API. Không còn vấn đề CPU local.
- [x] **torch nặng trong image** — không còn trong `backend/pyproject.toml`. `grep torch` chỉ
  khớp 1 comment lịch sử trong `app/rag/reranker.py`. OK.
- [x] **Structured logging thay vì print()** — `grep "print(" backend/app/` → 0 khớp. Toàn bộ
  code đã dùng `logging.getLogger(__name__)`. OK.

## Đã đúng sẵn (verified OK — không cần đổi)

- [x] **--workers 4 cho uvicorn** — có sẵn trong `docker-compose.prod.yml` (api command).
- [x] **restart: unless-stopped cho Redis** — có sẵn (`redis` service).
- [x] **uv.lock commit + --frozen** — `uv lock --check` PASS (123 packages resolved, không lệch)
  dù pyproject vừa thêm pytest-cov. CI (`ci.yml`) dùng `uv sync --frozen`. OK.
- [x] **alembic ở main dependencies** — `alembic>=1.13.0` nằm trong `[project.dependencies]`
  (không phải dev). OK.
- [x] **Supabase pooler port 6543** — `.env.example` + comment `config.py` đều dùng 6543
  (PgBouncer transaction mode). `db/session.py` tự bật `statement_cache_size=0` + `ssl=require`
  khi phát hiện URL Supabase. OK.
- [x] **CI/CD pipeline** — `.github/workflows/ci.yml` (lint→unit→integration→docker build) +
  `cd.yml` (build/push ghcr → migrate → SSH deploy sau cờ `DEPLOY_ENABLED`) đúng kỳ vọng,
  đã fix ở session trước. Chỉ verify, không đụng.
- [x] **`.env` / accessKeys.csv không commit** — `git ls-files` không track file `.env*` hay
  `.csv` nào. `.gitignore` có `.env`, `.env.local`, `*.csv`. (Nhưng thiếu `.env.prod` — xem
  Pending bên dưới.)

## Đã Fixed

- [x] **.gitignore thiếu `.env.prod`** — `backend/.gitignore`: thêm `.env.prod` + `.env.*`
  (giữ `!.env.example`). Commit `fix: harden prod config`.
- [x] **SECRET_KEY production guard** — `backend/app/core/config.py`: `model_validator` chặn
  deploy khi `APP_ENV=production` mà SECRET_KEY default/yếu (<32 chars) hoặc `DEBUG=true`.
  Verified: dev pass, prod+weak fail, prod+strong pass. Commit `fix: harden prod config`.
- [x] **Health check thật (DB + Redis + Qdrant)** — `backend/app/main.py`: ping DB (`SELECT 1`),
  Redis (`PING`), Qdrant (`get_collections` trong executor), gather song song, trả 503
  `degraded` + per-component status nếu có service down. Thêm `app/core/redis_client.py`
  (async redis client cached, không thêm dep). Verified end-to-end qua TestClient (503 khi
  Qdrant down, body có components). Commit `fix: implement real health check`.
- [x] **JWT blacklist cho logout** — `security.py` thêm `jti` vào token; `token_blacklist.py`
  lưu jti vào Redis với TTL tới `exp`; `dependencies.py` check blacklist → 401; `POST
  /auth/logout` (idempotent 204). Verified e2e. Commit `feat: JWT logout with Redis blacklist`.
- [x] **Rate limiting `/chat` + `/documents/upload`** — `rate_limit.py` limiter Redis
  fixed-window (per-user, fail-open, 429 + Retry-After), gắn vào 2 route. Limits tunable trong
  config (`CHAT_RATE_LIMIT_PER_MINUTE=20`, `UPLOAD_RATE_LIMIT_PER_MINUTE=10`). Verified (3
  allowed / 2 blocked). Commit `feat: rate limiting`.
- [x] **Review DB_POOL_SIZE vs tổng connections** — Đã phân tích: API(4 workers)≈60 +
  Celery worker(prefork 4, cùng async engine qua asyncio.run)≈60 ≈ 120 client conn. **Chấp
  nhận được** vì cổng 6543 (Supavisor transaction-mode) multiplex xuống ít Postgres backend;
  "60" free tier là giới hạn phía Postgres, không phải client. KHÔNG đổi số (tránh giảm
  throughput). Đã thêm comment cảnh báo trong `config.py`: nếu đổi sang 5432 trực tiếp phải giảm.
  Commit `docs: document DB pool connection math`.

## Đã Fixed — Session 2 (hardening bảo mật)

- [x] **Data isolation `list_documents()` + ownership enforce upload/delete/reindex** — model
  `documents.owner_id` (FK users, SET NULL, indexed, nullable) + migration `a1b2c3d4e5f6`.
  `document_service._get_owned_or_404` enforce ownership (404 không 403 để không lộ tồn tại);
  list/get/download/delete/reindex đều owner-scoped; admin thấy/quản lý tất cả; doc legacy
  owner=NULL ẩn với non-admin. Thêm `get_current_user`/`CurrentUserDep`. Access control =
  ownership-based (user chọn: không role-gate; mọi user đăng nhập mutate được doc của mình).
  5 unit test isolation pass; mypy + ruff clean. Commit `feat: document data isolation`.
  **Đã nối tiếp ở session 3:** RAG retriever giờ đã owner-scoped (xem dưới).

## Đã Fixed — Session 3 (hardening bảo mật)

- [x] **Data isolation RAG retrieval (owner-scope `/chat`)** — nối tiếp isolation documents session 2.
  Chunk mang `owner_id` trong payload Qdrant + property node Neo4j (ghi lúc ingest:
  `workers/tasks/ingestion.py` + `ingestion/graph_indexer.py`). `HybridRetriever._build_qdrant_filter`
  (helper thuần, có test) + owner filter trong Cypher `_graph_search`; param `owner_id` trên
  `_dense_search`/`_graph_search`/`retrieve`. `AgentState.owner_id` chảy từ `chat_service`
  (owner_id=user_id; admin → None → không filter) → `retriever_node`. `chat.py` API đổi sang
  `CurrentUserDep` + truyền `is_admin`. Kết quả: `/chat` chỉ truy hồi chunk của chính user; admin
  thấy tất cả; chunk legacy (payload thiếu owner_id) ẩn với non-admin. 7 unit test mới
  (`test_retrieval_isolation.py`: build-filter + dense-search gắn filter) — tổng 25 unit test pass;
  mypy + ruff clean. Commit `feat: RAG retrieval data isolation`.
  **⚠️ Lưu ý deploy:** chunk cũ ingest trước thay đổi này thiếu `owner_id` trong payload → non-admin
  không truy hồi được (an toàn nhưng "mất" kết quả). Reindex các doc để backfill payload owner_id.

## Đang Pending — làm tiếp từ đây

_(Hết mục code-fixable trong checklist gốc + 3 mục hardening bảo mật ưu tiên cao — data isolation
nay end-to-end cả documents lẫn retrieval. Session sau: xem "Gợi ý" cuối file — còn citations table,
qdrant SDK, SSE streaming.)_

## Blocked — cần user làm thủ công (không thể fix bằng code)

- [ ] **SECRET_KEY random 64+ chars** — chạy `openssl rand -hex 32`, đặt vào `.env.prod` trên
  server (hoặc secrets manager). Code chỉ có thể thêm guard chặn secret rác (xem Pending), không
  thể tự sinh & lưu secret an toàn thay user.
- [ ] **DEBUG=false, APP_ENV=production** — đặt trong `.env.prod` trên server. Default trong
  `config.py` đã an toàn (`DEBUG=False`, `APP_ENV=development`); `.env.example` để `DEBUG=true`
  là template dev, không dùng cho prod.
- [ ] **ALLOWED_ORIGINS đúng domain production** — đặt domain thật (không localhost) trong
  `.env.prod`. Format JSON array, vd `["https://app.example.com"]`.
- [ ] **Bật deploy job + provisioning server** — `cd.yml` deploy job skip tới khi tạo repo
  variable `DEPLOY_ENABLED=true` + 3 secrets `DEPLOY_HOST`/`DEPLOY_USER`/`DEPLOY_SSH_KEY`, và
  chuẩn bị server có `.env.prod` tại `/opt/rag`. Việc SSH/tạo secret nằm ngoài khả năng code.

---

## Gợi ý cho session sau (hardening tiếp — nằm ngoài checklist gốc)

Checklist production-readiness gốc + 3 mục bảo mật ưu tiên cao đã xong (data isolation nay
end-to-end: cả `list_documents` lẫn `/chat` retrieval đều owner-scoped). Nếu muốn hardening tiếp,
các mục technical-debt còn lại trong `SKILL.md`:
- **Backfill owner_id cho chunk cũ** — sau khi deploy data-isolation retrieval, chunk ingest trước
  thay đổi thiếu `owner_id` trong payload Qdrant/Neo4j → non-admin không truy hồi được. Reindex các
  doc (hoặc script backfill payload) để khôi phục. Vận hành, không phải code thuần.
- Citations lưu bằng HTML comment thay vì bảng `citations` (fragile).
- `_dense_search()` chuyển từ httpx thủ công sang `qdrant_client` SDK.
- SSE streaming cho `/chat`; nạp conversation history vào `AgentState` (multi-turn).

Lệnh tiếp tục: mở Claude Code, chạy → "đọc .claude/tasks/production-readiness-audit.md và
tiếp tục từ mục Pending đầu tiên" (hiện Pending code-fixable đã hết → chuyển sang mục hardening
ở trên hoặc xử lý các mục Blocked cần thao tác thủ công).
