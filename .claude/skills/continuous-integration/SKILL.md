---
name: continuous-integration
description: Giải thích, sửa, hoặc debug pipeline CI của monorepo Enterprise Knowledge RAG. Dùng khi user hỏi về GitHub Actions, CI đang fail, muốn thêm job CI mới, hoặc sửa .github/workflows/ci.yml.
---

# Continuous integration

Workflow: `.github/workflows/ci.yml` (repo root — **không** phải `backend/.github/`, GitHub chỉ
scan workflow ở đúng repo root nơi có `.git`).

Trigger: push/PR vào `main`/`develop`, chỉ khi đổi file trong `backend/**` (path filter — sửa
frontend không trigger CI backend).

## Job flow

```
lint (ruff check + format + mypy non-blocking)
  ├─→ test-unit (SQLite in-memory, không cần service ngoài)
  └─→ test-integration (Postgres + Qdrant + Redis + Neo4j + LocalStack — TẤT CẢ container
         tạm trong CI job, không có secret/cloud dependency nào)
         └─→ docker-build (context: ./backend, validate build only, không push)
```

Toàn bộ jobs chạy `defaults.run.working-directory: backend`.

## Quyết định kiến trúc: local container, không dùng Supabase/Qdrant Cloud cho CI

Đã cân nhắc và chốt: CI dùng **container tạm hoàn toàn** (`postgres:16-alpine`,
`qdrant/qdrant`), không kết nối Supabase staging hay Qdrant Cloud thật. Lý do:

- Qdrant self-host và Qdrant Cloud là cùng 1 engine — container local cho fidelity gần như
  tương đương, không cần trả phí network/quota.
- Điểm khác biệt thật duy nhất của Supabase là hành vi PgBouncer transaction-mode
  (`statement_cache_size=0`, xem `backend/app/db/session.py::_connect_args()`) — nhưng đây là
  logic string-matching thuần túy, đã được verify bằng **unit test**
  (`backend/app/tests/unit/test_db_session.py`), không cần container PgBouncer thật (dựng
  PgBouncer sống trong CI dễ flaky vì GitHub Actions không đảm bảo thứ tự khởi động giữa các
  service với nhau).
- Container tạm bị hủy hoàn toàn sau mỗi job → không rủi ro data tích lũy, không cần secret,
  không phụ thuộc mạng ra ngoài → nhanh và ổn định hơn.

Nếu sau này cần độ tin cậy sát production hơn nữa (ví dụ trước khi tag release), cân nhắc thêm
1 workflow riêng chạy smoke test nhắm vào Supabase/Qdrant Cloud thật — không gộp vào `ci.yml`
hiện tại để tránh chặn mọi PR bằng dependency cloud.

OpenAI vẫn dùng fake key (`sk-test-fake-key-for-ci`) trong mọi job — test nào chạm vào
`get_llm()`/`get_embedder()` phải mock ở test level, không gọi OpenAI thật.

## Debug CI fail

1. **Lint fail**: `cd backend && uv run ruff check .` và `uv run ruff format . --check` local
   trước khi push.
2. **Unit test fail**: `uv run pytest app/tests/unit/ -v`.
3. **Integration test fail**:
   - Lỗi ở `alembic upgrade head` → thường là migration mới có vấn đề cú pháp, không liên quan
     staging/production vì DB giờ là container local sạch mỗi lần chạy.
   - Lỗi kết nối Postgres/Qdrant/Redis/Neo4j → kiểm tra healthcheck của service tương ứng trong
     `services:` block — có thể container chưa kịp healthy trước khi step chạy.
4. **Docker build fail**: build local trước — `cd backend && docker build -t rag-backend:test .`
   — nếu `uv.lock` không khớp `pyproject.toml` sẽ fail ở đây trước khi CI báo.
5. **Cache miss liên tục**: cache key là `hashFiles('backend/uv.lock')` — sửa `pyproject.toml`
   mà quên `uv lock` sẽ khiến `uv sync --frozen` fail vì lockfile không khớp.

## Khi thêm job CI mới

- Thêm vào `.github/workflows/ci.yml`, không tạo file workflow mới trừ khi job đó độc lập hoàn
  toàn (khác trigger, khác concern).
- Nếu job cần thêm biến môi trường, copy từ block `env:` của job `test-integration` hiện có để
  không thiếu biến (Settings dùng pydantic-settings, thiếu biến bắt buộc sẽ crash khi import
  `app.core.config`).
- Ưu tiên container tạm (self-host image) thay vì cloud thật khi thêm service mới, theo nguyên
  tắc đã chốt ở trên — chỉ dùng cloud thật khi có lý do kỹ thuật cụ thể không thể tái tạo bằng
  container local.
