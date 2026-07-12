# GitHub Actions — Setup Guide

## 1. Secrets cần thêm vào GitHub

Vào **Settings → Secrets and variables → Actions → New repository secret**

CI (`ci.yml`) không cần secret nào. Integration test hiện chỉ dùng PostgreSQL container tạm;
thêm service khác khi có test ingestion/retrieval tương ứng. Secret chỉ cần cho **deploy**
(`cd.yml`):

### Deploy secrets (dùng trong `cd.yml`)

| Secret | Mô tả | Ví dụ |
|---|---|---|
| `DEPLOY_HOST` | IP hoặc domain server production | `203.0.113.10` |
| `DEPLOY_USER` | SSH user trên server | `ubuntu` |
| `DEPLOY_SSH_KEY` | Private key SSH (nội dung file `~/.ssh/id_rsa`) | `-----BEGIN OPENSSH...` |
| `DATABASE_URL` | Supabase connection string production (port 6543 — PgBouncer) |

### App secrets (inject vào container qua `.env.prod` trên server — KHÔNG phải GitHub Secrets)

| Biến | Mô tả |
|---|---|
| `DATABASE_URL` | Supabase connection string production |
| `SECRET_KEY` | Random 64+ chars: `openssl rand -hex 32` |
| `OPENAI_API_KEY` | OpenAI API key |
| `QDRANT_URL` / `QDRANT_API_KEY` | Qdrant Cloud production |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_S3_BUCKET_NAME` | S3 raw file storage production |
| `AWS_S3_ENDPOINT_URL` | Để trống trong production để dùng AWS S3 thật |
| `NEO4J_PASSWORD` | Neo4j password (đổi khỏi mặc định) |
| `LANGCHAIN_API_KEY` | LangSmith API key (nếu dùng) |

---

## 2. Setup server lần đầu

SSH vào server và chạy:

```bash
# Tạo thư mục deploy
mkdir -p /opt/rag
cd /opt/rag

# Tạo .env.prod từ template — điền giá trị thật.
# docker-compose.prod.yml sẽ được CD tự động đồng bộ vào /opt/rag.
cp /path/to/backend/.env.example .env.prod
nano .env.prod   # sửa tất cả giá trị placeholder

# Đảm bảo Docker Compose hỗ trợ `up --wait`
docker --version
docker compose version
```

---

## 3. GitHub Environment

CD workflow dùng `environment: production` để yêu cầu approval trước khi deploy.

Vào **Settings → Environments → New environment → production**:
- Bật **Required reviewers** (thêm tên reviewer)
- Bật **Deployment branches and tags**: cho phép branch `main` và tag `v*.*.*`

---

## 4. Flow CI/CD tổng quan

CI (PR vào `main`/`develop`, push `develop`, hoặc được CD gọi): kiểm tra lockfile/actionlint
→ lint + mypy → unit tests với coverage gate → integration auth với PostgreSQL tạm
→ Docker build validate.

CD (push `main`, tag version hoặc chạy thủ công): gọi CI cho đúng commit → build & push image
lên GHCR → chờ approval → `alembic upgrade head` trên Supabase production → đồng bộ Compose
→ deploy đúng image digest bất biến → chờ container healthy → kiểm tra `/health`.

---

## 5. Trigger deploy thủ công

```bash
# Deploy từ tag version
git tag v1.0.0
git push origin v1.0.0
```

Hoặc vào **Actions → CD — Deploy to production → Run workflow**.
