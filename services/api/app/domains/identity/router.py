"""Public identity endpoints introduced by the unified auth contract."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.identity.challenges import ChallengeError, ChallengeService, RedisChallengeStore
from app.domains.identity.security import PasswordHasher, PasswordPolicyError
from app.domains.identity.service import PasswordAuthenticationError, PasswordService
from app.domains.identity.sms import DemoSmsProvider, TencentSmsProvider
from app.domains.identity.types import CurrentIdentity
from app.gateway.auth import get_current_user
from app.gateway.jwt import create_token_with_role
from app.gateway.redis import get_redis
from app.gateway.schemas import ApiResponse
from app.models.database import get_db
from app.models.role_binding import RoleBinding
from app.models.user import User

router = APIRouter()


class SmsChallengeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    purpose: str


class PasswordSetRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class PasswordLoginRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


class PasswordResetRequest(PasswordSetRequest):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(pattern=r"^\d{6}$")


def get_challenge_service() -> ChallengeService:
    if settings.auth_sms_provider == "demo":
        provider = DemoSmsProvider(
            environment=settings.app_env,
            allowlist=set(settings.auth_demo_sms_phone_list),
        )
    else:
        provider = TencentSmsProvider()
    return ChallengeService(
        store=RedisChallengeStore(get_redis()),
        provider=provider,
        pepper=settings.auth_otp_pepper,
    )


def get_password_service() -> PasswordService:
    return PasswordService(PasswordHasher())


def _password_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PasswordPolicyError):
        return HTTPException(
            status_code=400,
            detail={"code": 40001, "error_key": exc.error_key, "message": exc.message},
        )
    if isinstance(exc, PasswordAuthenticationError):
        status_code = 423 if exc.error_key == "AUTH_PASSWORD_LOCKED" else 401
        return HTTPException(
            status_code=status_code,
            detail={"code": 40101, "error_key": exc.error_key, "message": exc.message},
        )
    raise exc


@router.post("/challenges/sms", response_model=ApiResponse)
async def create_sms_challenge(
    body: SmsChallengeRequest,
    request: Request,
    service: ChallengeService = Depends(get_challenge_service),
):
    try:
        issued = await service.create(
            body.phone,
            body.purpose,
            ip_prefix=request.client.host if request.client else "unknown",
        )
    except ChallengeError as exc:
        detail = {
            "code": 42901 if exc.http_status == 429 else 50301 if exc.http_status == 503 else 40002,
            "error_key": exc.error_key,
            "message": exc.message,
        }
        if exc.retry_after is not None:
            detail["retry_after"] = exc.retry_after
        raise HTTPException(status_code=exc.http_status, detail=detail) from None
    return ApiResponse(
        code=0,
        message="sent",
        data={
            "challenge_id": issued.challenge_id,
            "expires_in": issued.expires_in,
            "retry_after": issued.retry_after,
            **({"demo_code": issued.demo_code} if issued.demo_code else {}),
        },
    )


@router.post("/password/set", response_model=ApiResponse)
async def set_password(
    body: PasswordSetRequest,
    current_user: CurrentIdentity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: PasswordService = Depends(get_password_service),
):
    try:
        await service.set_password(db, current_user.user_id, body.password)
    except PasswordPolicyError as exc:
        raise _password_error(exc) from None
    return ApiResponse(code=0, message="ok", data={"password_set": True})


@router.post("/login/password", response_model=ApiResponse)
async def login_password(
    body: PasswordLoginRequest,
    db: AsyncSession = Depends(get_db),
    service: PasswordService = Depends(get_password_service),
):
    try:
        user = await service.authenticate(db, body.phone, body.password)
    except PasswordAuthenticationError as exc:
        raise _password_error(exc) from None
    bindings = (
        await db.execute(
            select(RoleBinding).where(
                RoleBinding.user_id == user.id,
                RoleBinding.status == "approved",
                RoleBinding.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    approved_roles = [binding.role for binding in bindings]
    if not approved_roles:
        raise HTTPException(
            status_code=403,
            detail={
                "code": 40300,
                "error_key": "AUTH_ROLE_NOT_APPROVED",
                "message": "账号没有已批准角色",
            },
        )
    active_role = (
        user.last_active_role
        if user.last_active_role in approved_roles
        else "student"
        if "student" in approved_roles
        else approved_roles[0]
    )
    token = create_token_with_role(
        str(user.id),
        active_role,
        security_version=user.security_version,
    )
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "access_token": token,
            "token": token,
            "expires_in": settings.auth_access_token_minutes * 60,
            "user": {
                "id": str(user.id),
                "nickname": user.nickname or "",
                "active_role": active_role,
                "roles": [
                    {"role": binding.role, "status": binding.status, "verified": True}
                    for binding in bindings
                ],
            },
        },
    )


@router.post("/password/reset", response_model=ApiResponse)
async def reset_password(
    body: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
    challenges: ChallengeService = Depends(get_challenge_service),
    passwords: PasswordService = Depends(get_password_service),
):
    try:
        await challenges.consume(
            body.challenge_id,
            body.phone,
            "password_reset",
            body.code,
        )
    except ChallengeError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={"code": 40002, "error_key": exc.error_key, "message": exc.message},
        ) from None
    user = (
        await db.execute(select(User).where(User.phone == body.phone, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is not None:
        try:
            await passwords.reset_password(db, user.id, body.password)
        except PasswordPolicyError as exc:
            raise _password_error(exc) from None
    return ApiResponse(code=0, message="ok", data={"password_reset": True})
