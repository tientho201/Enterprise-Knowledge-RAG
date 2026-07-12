---
name: code-review
description: Review code trước khi merge PR trong monorepo Enterprise Knowledge RAG. Dùng khi user yêu cầu "review code này", "review PR", hoặc trước khi tự báo 1 thay đổi lớn là hoàn thành. Checklist chung cho cả backend và frontend — dùng thêm skill rag-review nếu PR đụng vào RAG pipeline, hoặc security-auditor agent nếu đụng vào auth/RBAC.
---

# Code review checklist

## Backend (Python)

- [ ] Layer separation: route (`app/api/`) không có DB query hay business logic; service
      (`app/services/`) không có SQL trực tiếp — gọi qua repository.
- [ ] LLM calls chỉ qua `get_llm()` (`app/llm/factory.py`) — không import `openai` trực tiếp ở
      chỗ khác.
- [ ] Async/sync boundary: code chạy trong FastAPI route/service phải async-safe. boto3, sync
      OpenAI client cần wrap `run_in_executor` (xem `app/storage/s3_client.py` làm mẫu) — không
      gọi thẳng.
- [ ] Celery task mới: có `bind=True`, `autoretry_for`, `retry_backoff=True`, và idempotent
      (chạy lại nhiều lần không gây side-effect trùng lặp).
- [ ] Không thêm dependency nặng (torch, sentence-transformers, v.v.) vào `pyproject.toml` mà
      không có lý do rõ ràng — project từng phải dọn ~2.5GB vì việc này.
- [ ] `ruff check` và `ruff format --check` sạch trước khi coi là xong (`cd backend && uv run
      ruff check . && uv run ruff format . --check`).

## Frontend (Next.js 16 / React 19)

- [ ] `frontend/AGENTS.md` cảnh báo: đây là Next.js version có breaking changes so với training
      data — kiểm tra `node_modules/next/dist/docs/` cho API mới trước khi dùng pattern cũ.
- [ ] `npm run lint` (eslint) và `npm run typecheck` (tsc --noEmit) sạch.
- [ ] Style dùng Tailwind + shadcn/radix-ui theo `components.json` — không tự viết CSS module
      song song nếu component tương đương đã có trong `components/`.

## Chung cho cả hai

- [ ] Không hardcode secret/API key trong code — luôn qua biến môi trường.
- [ ] Nếu sửa endpoint API, kiểm tra `frontend/endpointAPIbe.json` (contract giữa 2 phía) có cần
      update theo không.
- [ ] Đổi kiến trúc/dependency lớn → cập nhật skill `enterprise-knowledge-rag` (bảng technical
      debt hoặc quyết định kiến trúc) để không bị lệch khỏi thực tế code.
