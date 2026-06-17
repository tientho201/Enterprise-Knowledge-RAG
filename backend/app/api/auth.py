from fastapi import APIRouter

from app.core.dependencies import CurrentUserIdDep, DbDep
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(body: RegisterRequest, db: DbDep):
    service = AuthService(db)
    return await service.register(body.email, body.password, body.full_name)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: DbDep):
    service = AuthService(db)
    return await service.login(body.email, body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshTokenRequest, db: DbDep):
    service = AuthService(db)
    return await service.refresh(body.refresh_token)


@router.get("/me", response_model=UserResponse)
async def me(user_id: CurrentUserIdDep, db: DbDep):
    service = AuthService(db)
    return await service.get_current_user(user_id)
