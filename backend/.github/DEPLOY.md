# GitHub Actions — Setup Guide

## 1. Secrets cần thêm vào GitHub

Vào **Settings → Secrets and variables → Actions → New repository secret**

### Deploy secrets (dùng trong CD workflow)

| Secret | Mô tả | Ví dụ |
|---|---|---|
| `DEPLOY_HOST` | IP hoặc domain server production | `203.0.113.10` |
| `DEPLOY_USER` | SSH user trên server | `ubuntu` |
| `DEPLOY_SSH_KEY` | Private key SSH (nội dung file `~/.ssh/id_rsa`) | `-----BEGIN OPENSSH...` |

### App secrets (inject vào container qua `.env.prod`)

| Secret | Mô tả |
|---|---|
| `DATABASE_URL` | Supabase connection string (port 6543 — PgBouncer) |
| `SECRET_KEY` | Random 64+ chars: `openssl rand -hex 32` |
| `OPENAI_API_KEY` | OpenAI API key |
| `QDRANT_API_KEY` | Qdrant Cloud API key |
| `QDRANT_URL` | Qdrant Cloud cluster URL |
| `MINIO_ACCESS_KEY` | MinIO username (đổi khỏi minioadmin) |
| `MINIO_SECRET_KEY` | MinIO password (đổi khỏi minioadmin) |
| `NEO4J_PASSWORD` | Neo4j password (đổi khỏi neo4j_password) |
| `LANGCHAIN_API_KEY` | LangSmith API key (nếu dùng) |

---

## 2. Setup server lần đầu

SSH vào server và chạy:

```bash
# Tạo thư mục deploy
mkdir -p /opt/rag
cd /opt/rag

# Tạo .env.prod từ template — điền giá trị thật
cp /path/to/.env.example .env.prod
nano .env.prod   # sửa tất cả giá trị placeholder

# Đảm bảo Docker và Docker Compose đã cài
docker --version
docker compose version
```

---

## 3. GitHub Environment

CD workflow dùng `environment: production` để yêu cầu approval trước khi deploy.

Vào **Settings → Environments → New environment → production**:
- Bật **Required reviewers** (thêm tên reviewer)
- Bật **Deployment branches**: chỉ cho phép branch `main`

---

## 4. Flow CI/CD tổng quan

```
Push to main / PR
       │
       ▼
  ┌─── CI ──────────────────────────────┐
  │  lint (ruff check + format + mypy)  │
  │       │                             │
  │   ┌───┴───┐                         │
  │   ▼       ▼                         │
  │ unit   integration                  │
  │ tests  tests (Redis+MinIO+Neo4j)    │
  │   └───┬───┘                         │
  │       ▼                             │
  │  docker build (validate only)       │
  └─────────────────────────────────────┘
       │ (chỉ khi push to main)
       ▼
  ┌─── CD ──────────────────────────────┐
  │  build & push image → ghcr.io       │
  │       │                             │
  │       ▼                             │
  │  alembic upgrade head               │
  │       │                             │
  │       ▼ (require approval)          │
  │  SSH deploy → docker compose up     │
  │  health check /health               │
  └─────────────────────────────────────┘
```

---

## 5. Trigger deploy thủ công

```bash
# Deploy từ tag version
git tag v1.0.0
git push origin v1.0.0
```

Hoặc vào **Actions → CD — Deploy to production → Run workflow**.
