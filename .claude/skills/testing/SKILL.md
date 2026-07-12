---
name: testing
description: Chạy và viết test cho monorepo Enterprise Knowledge RAG. Dùng khi user yêu cầu "chạy test", "viết unit test", "test coverage", hoặc trước khi báo 1 task hoàn thành nếu task đó sửa code trong backend/app/ hoặc frontend/. Backend dùng pytest qua uv, frontend chưa có test runner cấu hình.
---

# Testing

## Backend (pytest qua uv)

Luôn chạy từ `backend/`:

```bash
cd backend

# toàn bộ test
uv run pytest

# chỉ unit test (không cần service ngoài — DB dùng sqlite in-memory)
uv run pytest app/tests/unit/ -v

# chỉ integration test (cần Redis + Neo4j chạy sẵn, xem docker-compose.yml)
uv run pytest app/tests/integration/ -v

# với coverage
uv run pytest --cov=app --cov-report=term-missing
```

Config: `backend/pyproject.toml` → `[tool.pytest.ini_options]`, `testpaths = ["app/tests"]`,
`asyncio_mode = "auto"` (không cần `@pytest.mark.asyncio` thủ công).

**Trạng thái thật**: `app/tests/unit/` và `app/tests/integration/` hiện chỉ có vài file stub
(`test_chunker.py`, `test_services.py`, `test_auth.py`) — CI đang "pass" nhưng coverage thực tế
rất thấp. Khi thêm code mới ở service/repository/agent nào, ưu tiên viết test tương ứng thay vì
giả định CI xanh là đủ.

**Integration test cần service**: Redis + Neo4j từ `docker-compose.yml`:
```bash
cd backend
docker compose up -d redis neo4j
```

## Frontend (Next.js)

`frontend/package.json` **chưa có script `test`**. Nếu cần thêm test, hỏi user muốn dùng
Vitest, Jest, hay Playwright trước khi tự chọn — chưa có convention nào được thiết lập.

Có sẵn:
```bash
cd frontend
npm run lint       # eslint
npm run typecheck  # tsc --noEmit
```

## Khi nào bắt buộc chạy test trước khi báo "xong"

- Sửa file trong `backend/app/services/`, `backend/app/repositories/`, `backend/app/agents/`
  → chạy `uv run pytest app/tests/unit/ -v` tối thiểu.
- Sửa `backend/app/api/*` → nếu có integration test liên quan, chạy luôn.
- Sửa frontend → chạy `npm run typecheck` tối thiểu (bắt lỗi type nhanh, không cần build đầy đủ).
