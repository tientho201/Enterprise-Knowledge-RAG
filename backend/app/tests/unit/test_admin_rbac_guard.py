"""
Guard phân quyền cho TOÀN BỘ router admin (T12): quyền admin được ép ở cấp router
qua `dependencies=[Depends(require_role(UserRole.admin))]` trong app/api/admin.py,
không còn kiểm thủ công từng route. Test duyệt mọi route `/api/v1/admin*` đang đăng
ký trong app — route mới thêm vào router này tự động được kiểm, không cần sửa test.

Cùng kỹ thuật cô lập DB như test_admin_users.py (SQLite in-memory, patch
AsyncSessionLocal đã bind trong app.core.dependencies).
"""

import re
import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.models.user import User, UserRole

ADMIN_PREFIX = "/api/v1/admin"
# Số route admin tại thời điểm viết test. Chỉ dùng làm sàn (>=) để bắt trường hợp
# bộ lọc route hỏng và test "pass" vì không duyệt route nào.
MIN_ADMIN_ROUTES = 6
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest_asyncio.fixture
async def isolated_app_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # /admin/jobs gọi celery_app.control.inspect() (cần broker thật) — thay bằng mock
    # để request của admin không treo/nổ vì hạ tầng. Không ảnh hưởng tới kiểm quyền.
    fake_celery = MagicMock()
    fake_celery.control.inspect.return_value.active.return_value = {}
    fake_celery.control.inspect.return_value.reserved.return_value = {}

    with (
        patch("app.core.dependencies.AsyncSessionLocal", session_factory),
        patch("app.api.admin.celery_app", fake_celery),
    ):
        from app.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session_factory

    await engine.dispose()


async def _create_user(session_factory, *, role: UserRole) -> tuple[str, str]:
    async with session_factory() as db:
        user = User(
            email=f"{role.value}-{uuid.uuid4().hex}@test.local",
            password_hash="unused",
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id
    return user_id, create_access_token(user_id)


def _admin_endpoints() -> list[tuple[str, str]]:
    """(method, path) của mọi route admin đang đăng ký, path param đã thay bằng giá
    trị giả.

    Lấy từ OpenAPI schema chứ không duyệt `app.routes`: từ FastAPI 0.137 router được
    include nằm trong wrapper nội bộ `_IncludedRouter` nên `app.routes` không còn
    phẳng (không thấy route con). Route `include_in_schema=False` không có trong
    schema — được bắt bởi test_admin_router_routes_all_in_schema bên dưới.
    """
    from app.main import app

    endpoints: list[tuple[str, str]] = []
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith(ADMIN_PREFIX):
            continue
        concrete = re.sub(r"\{[^}]+\}", "does-not-exist", path)
        for method in sorted(operations):
            if method.upper() in HTTP_METHODS:
                endpoints.append((method.upper(), concrete))
    return endpoints


def test_admin_routes_are_discovered():
    endpoints = _admin_endpoints()
    assert len(endpoints) >= MIN_ADMIN_ROUTES, endpoints


def test_admin_router_declares_role_dependency():
    # Kiểm cấu trúc: guard nằm ở router (áp cho mọi route, kể cả route thêm sau),
    # và đúng là require_role của app/auth/rbac.py.
    from app.api.admin import router

    qualnames = [getattr(d.dependency, "__qualname__", "") for d in router.dependencies]
    assert any(q.startswith("require_role.") for q in qualnames), qualnames


def test_admin_router_routes_all_in_schema():
    # Mọi route khai báo trên router admin phải xuất hiện trong danh sách được duyệt
    # ở các test dưới; route ẩn khỏi schema sẽ làm test này đỏ thay vì lọt lưới.
    from app.api.admin import router
    from app.main import app

    declared = {f"/api/v1{route.path}" for route in router.routes if isinstance(route, APIRoute)}
    in_schema = {p for p in app.openapi()["paths"] if p.startswith(ADMIN_PREFIX)}
    assert declared
    assert declared == in_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.viewer, UserRole.editor])
async def test_non_admin_gets_403_on_every_admin_route(isolated_app_client, role):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=role)
    headers = {"Authorization": f"Bearer {token}"}

    endpoints = _admin_endpoints()
    assert endpoints
    got = {}
    for method, path in endpoints:
        resp = await client.request(method, path, headers=headers)
        got[f"{method} {path}"] = resp.status_code
    assert all(code == 403 for code in got.values()), got


@pytest.mark.asyncio
async def test_no_token_is_rejected_on_every_admin_route(isolated_app_client):
    client, _ = isolated_app_client

    endpoints = _admin_endpoints()
    assert endpoints
    got = {}
    for method, path in endpoints:
        resp = await client.request(method, path)
        got[f"{method} {path}"] = resp.status_code
    assert all(code in (401, 403) for code in got.values()), got


@pytest.mark.asyncio
async def test_admin_is_never_forbidden_on_admin_routes(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.admin)
    headers = {"Authorization": f"Bearer {token}"}

    endpoints = _admin_endpoints()
    assert endpoints
    got = {}
    for method, path in endpoints:
        resp = await client.request(method, path, headers=headers)
        got[f"{method} {path}"] = resp.status_code
    # Path giả / thiếu body nên 404/422 là hợp lệ; chỉ cần không bị chặn quyền.
    assert all(code not in (401, 403) for code in got.values()), got


@pytest.mark.asyncio
async def test_forbidden_detail_comes_from_require_role(isolated_app_client):
    client, session_factory = isolated_app_client
    _, token = await _create_user(session_factory, role=UserRole.viewer)

    resp = await client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Requires admin role or higher"


@pytest.mark.asyncio
async def test_token_of_missing_user_gets_404(isolated_app_client):
    # CÓ CHỦ ĐÍCH (người dùng duyệt phương án A của T12): token hợp lệ nhưng user
    # không còn trong DB nhận 404 "User not found" từ auth/rbac.py::require_role,
    # thay cho 403 "Admin access required" của require_admin cũ. Không có endpoint
    # xoá user nên nhánh này chỉ xảy ra khi xoá trực tiếp trong DB.
    client, _ = isolated_app_client
    token = create_access_token(str(uuid.uuid4()))

    resp = await client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


@pytest.mark.asyncio
async def test_role_check_runs_before_body_validation(isolated_app_client):
    # Dependency cấp router chạy trước khi validate body: non-admin gửi body sai
    # nhận 403 (trước T12 là 422, vì kiểm quyền nằm trong thân hàm). Nhờ vậy
    # non-admin không dò được schema của route admin.
    client, session_factory = isolated_app_client
    _, viewer_token = await _create_user(session_factory, role=UserRole.viewer)
    _, admin_token = await _create_user(session_factory, role=UserRole.admin)
    target_id, _ = await _create_user(session_factory, role=UserRole.viewer)
    url = f"/api/v1/admin/users/{target_id}/role"
    bad_body = {"role": "not-a-role"}

    viewer_resp = await client.patch(
        url, json=bad_body, headers={"Authorization": f"Bearer {viewer_token}"}
    )
    assert viewer_resp.status_code == 403

    # Đối chứng: cùng body đó với admin thì đúng là body không hợp lệ.
    admin_resp = await client.patch(
        url, json=bad_body, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert admin_resp.status_code == 422
