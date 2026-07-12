---
name: deployment
description: Giải thích, sửa, hoặc thực hiện deploy backend lên production. Dùng khi user hỏi về deploy, .github/workflows/cd.yml, docker-compose.prod.yml, hoặc setup server production. Chỉ áp dụng cho backend/ — frontend chưa có deployment pipeline được thiết lập.
---

# Deployment (backend)

Workflow: `.github/workflows/cd.yml` (repo root). Trigger: push vào `main` (chỉ khi đổi
`backend/**`) hoặc tag `v*.*.*`.

## Job flow

```
build-push (build image, context: ./backend, push lên ghcr.io)
  └─→ migrate (alembic upgrade head, environment: production — cần approval)
        └─→ deploy (SSH vào server, docker compose up, health check)
```

`migrate` và `deploy` đều dùng GitHub Environment `production` — cần setup **Required
reviewers** trong Settings → Environments để có approval gate trước khi chạm production.

## Secrets cần có (Settings → Secrets and variables → Actions)

| Secret | Dùng ở đâu |
|---|---|
| `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` | SSH vào server trong job `deploy` |
| `DATABASE_URL` | job `migrate` chạy alembic |
| Các biến trong `backend/.env.prod` trên server (không phải GitHub secret) | container `api`/`worker` đọc qua `env_file` |

Chi tiết đầy đủ: `.github/DEPLOY.md`.

## docker-compose.prod.yml (`backend/docker-compose.prod.yml`)

Chạy trên server, image pull từ ghcr.io (không build local):
- `api`: uvicorn 4 workers
- `worker`: Celery, concurrency=4
- `beat`: Celery scheduler
- `redis`, `neo4j`: self-hosted (Postgres/S3/Qdrant đều cloud managed, không có ở đây)

## Deploy thủ công (bypass CI, chỉ dùng khi khẩn cấp)

```bash
# trên server
cd /opt/rag
docker compose -f docker-compose.prod.yml pull api worker
docker compose -f docker-compose.prod.yml up -d --no-deps api worker
docker compose -f docker-compose.prod.yml exec -T api curl -sf http://localhost:8000/health
```

**Lưu ý**: health check hiện tại (`backend/app/main.py`) chỉ trả `{"status": "ok"}` cứng, không
check DB/Redis/Qdrant thật — nếu deploy xong mà DB connection string sai, health check vẫn báo
ok. Đây là known gap, xem bảng technical debt trong skill `enterprise-knowledge-rag`.

## Trước khi trigger deploy

- Xác nhận `alembic upgrade head` chạy được với `DATABASE_URL` production trước (chạy thử ở
  staging nếu có, hoặc review migration diff kỹ).
- Docker image build local trước để bắt lỗi sớm: `cd backend && docker build -t rag-backend:test .`
