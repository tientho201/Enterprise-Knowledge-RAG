# Production Readiness Audit

Cập nhật lần cuối: 2026-07-14 (session 1 — audit khởi tạo + bắt đầu fix)

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

_(chưa có — session này bắt đầu từ đây)_

## Đang Pending — làm tiếp từ đây

Thứ tự ưu tiên (code-fixable):

- [ ] **Health check thật (DB + Redis + Qdrant)** — `backend/app/main.py` hiện trả cứng
  `{"status":"ok"}`. CD dùng `/health` để xác nhận deploy → không đáng tin. CẦN: ping DB
  (`SELECT 1`), Redis (`PING`), Qdrant (`get_collections`), trả 503 nếu bất kỳ service down.
  Redis async client: dùng `redis.asyncio` (redis>=5 đã là dependency, không thêm dep mới).
  Qdrant: `get_qdrant_client().get_collections()` wrap trong executor (client sync).
- [ ] **Rate limiting cho `/chat` và `/documents/upload`** — chưa có. Rủi ro cost OpenAI/abuse.
  Kế hoạch: limiter dependency dựa trên Redis INCR + expiry (tái dùng `redis.asyncio`, KHÔNG
  thêm slowapi để tránh churn dependency/lock + phụ thuộc network resolve). Áp per-user/per-IP.
- [ ] **JWT blacklist cho logout** — `app/api/auth.py` chỉ có register/login/refresh/me, KHÔNG
  có logout. CẦN: `POST /auth/logout` đẩy jti/token vào Redis blacklist (TTL = thời gian còn
  lại của token), `get_current_user_id` check blacklist. (Cần thêm `jti`+`exp` vào token payload
  trong `security.py`.)
- [ ] **.gitignore thiếu `.env.prod`** — `docker-compose.prod.yml` đọc `.env.prod` nhưng
  `.gitignore` chỉ có `.env`, `.env.local` (pattern `.env` KHÔNG match `.env.prod`). Thêm
  `.env.prod` + `.env.*` để tránh commit nhầm secret production. (Nhỏ, an toàn.)
- [ ] **SECRET_KEY production guard** — `config.py` default `SECRET_KEY="changeme"`. Thêm
  validator: nếu `APP_ENV=production` mà SECRET_KEY còn là default/yếu (<32 chars) → fail sớm.
  Không tự sinh secret (đó là việc user), chỉ chặn deploy với secret rác.
- [ ] **Review DB_POOL_SIZE vs tổng connections** — pool_size=5 + overflow=10 = 15/process.
  API 4 uvicorn workers → peak 60 chỉ riêng API, cộng worker(concurrency=4)+beat. Cần xác nhận
  PgBouncer transaction mode (6543) đủ multiplex hay phải giảm số. Đánh giá, chỉ đổi nếu thật sự
  rủi ro (tránh giảm throughput vô cớ).

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
