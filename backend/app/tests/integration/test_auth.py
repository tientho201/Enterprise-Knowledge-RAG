import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.redis_client import get_redis
from app.db.session import AsyncSessionLocal
from app.models.user import User


async def _get_otp_code(email: str) -> str:
    """Đọc thẳng mã OTP từ Redis (không qua email thật) — hạ tầng test dùng Redis
    container thật (xem ci.yml job integration), .delay() chỉ enqueue chứ không
    có worker nào chạy trong lúc test nên SMTP thật không bao giờ được gọi."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
    redis = get_redis()
    code = await redis.get(f"otp:register:{user.id}")
    assert code is not None, "OTP không tồn tại trong Redis — register có dispatch task không?"
    return code


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    # Register — trả về trạng thái "đang chờ xác minh", chưa cho login ngay
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "test@example.com"

    # Login trước khi verify OTP phải bị chặn
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert resp.status_code == 403

    # Verify OTP sai -> 400
    resp = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "test@example.com", "otp_code": "000000"},
    )
    assert resp.status_code == 400

    # Verify OTP đúng -> trả token luôn (auto-login)
    otp_code = await _get_otp_code("test@example.com")
    resp = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "test@example.com", "otp_code": otp_code},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()

    # Login bình thường sau khi verify
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    # Phụ thuộc user "test@example.com" đã được verify ở test_register_and_login
    # (cùng DB thật trong suốt integration job, chạy tuần tự theo thứ tự file).
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    payload = {"email": "dup@example.com", "password": "password123"}

    # Đăng ký lần đầu — chưa verify
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201

    # Đăng ký lại trong lúc CHƯA verify — cho phép (gửi lại OTP), không phải lỗi
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201

    # Verify xong rồi mới thật sự là "đã có tài khoản" -> đăng ký lại phải 409
    otp_code = await _get_otp_code("dup@example.com")
    resp = await client.post(
        "/api/v1/auth/verify-otp",
        json={"email": "dup@example.com", "otp_code": otp_code},
    )
    assert resp.status_code == 200

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_resend_otp_cooldown(client: AsyncClient):
    payload = {"email": "resend@example.com", "password": "password123"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201

    # Gọi lại resend ngay lập tức -> đang trong cooldown -> 429
    resp = await client.post("/api/v1/auth/resend-otp", json={"email": "resend@example.com"})
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    # Job này chỉ provision Postgres (xem comment ci.yml) — Redis/Qdrant chưa
    # có nên /health có thể trả 503 "degraded". Chỉ assert phần DB (thứ CI
    # job này thực sự kiểm chứng được) thay vì yêu cầu toàn bộ stack "ok".
    resp = await client.get("/health")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["components"]["database"] == "ok"
