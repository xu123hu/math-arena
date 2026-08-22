"""Public identity endpoints introduced by the unified auth contract."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.identity.challenges import ChallengeError, ChallengeService, RedisChallengeStore
from app.domains.identity.security import PasswordHasher, PasswordPolicyError
from app.domains.identity.service import PasswordAuthenticationError, PasswordService
from app.domains.identity.sessions import (
    SessionError,
    SessionService,
    clear_session_cookies,
    set_session_cookies,
    validate_csrf,
)
from app.domains.identity.sms import DemoSmsProvider, TencentSmsProvider
from app.domains.identity.types import CurrentIdentity
from app.gateway.auth import get_current_user
from app.gateway.redis import get_redis
from app.gateway.schemas import ApiResponse
from app.models.database import get_db
from app.models.identity import AuthSession
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


def get_session_service() -> SessionService:
    return SessionService(refresh_pepper=settings.auth_refresh_token_pepper)


def _secure_cookies() -> bool:
    return settings.app_env in {"staging", "production"}


def _session_error(exc: SessionError) -> HTTPException:
    status_code = 403 if exc.error_key == "AUTH_CSRF_INVALID" else 401
    return HTTPException(
        status_code=status_code,
        detail={"code": 40301 if status_code == 403 else 40100, "error_key": exc.error_key, "message": exc.message},
    )


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
    response: Response,
    db: AsyncSession = Depends(get_db),
    service: PasswordService = Depends(get_password_service),
    sessions: SessionService = Depends(get_session_service),
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
    issued = await sessions.issue(db, user, active_role, remember=body.remember)
    set_session_cookies(response, issued, secure=_secure_cookies())
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "access_token": issued.access_token,
            "token": issued.access_token,
            "expires_in": issued.access_expires_in,
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


@router.post("/token/refresh", response_model=ApiResponse)
async def refresh_token(
    response: Response,
    ma_refresh: str | None = Cookie(default=None),
    ma_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: AsyncSession = Depends(get_db),
    service: SessionService = Depends(get_session_service),
):
    try:
        validate_csrf(ma_csrf, x_csrf_token)
        if not ma_refresh:
            raise SessionError("AUTH_REFRESH_INVALID", "刷新凭据缺失")
        issued = await service.rotate(db, ma_refresh)
    except SessionError as exc:
        if exc.persist_changes:
            await db.commit()
        if exc.error_key != "AUTH_CSRF_INVALID":
            clear_session_cookies(response, secure=_secure_cookies())
        raise _session_error(exc) from None
    set_session_cookies(response, issued, secure=_secure_cookies())
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(
        code=0,
        message="ok",
        data={"access_token": issued.access_token, "expires_in": issued.access_expires_in},
    )


@router.post("/logout", response_model=ApiResponse)
async def logout(
    response: Response,
    ma_refresh: str | None = Cookie(default=None),
    ma_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: AsyncSession = Depends(get_db),
    service: SessionService = Depends(get_session_service),
):
    try:
        validate_csrf(ma_csrf, x_csrf_token)
    except SessionError as exc:
        raise _session_error(exc) from None
    if ma_refresh:
        await service.revoke_by_refresh(db, ma_refresh)
    clear_session_cookies(response, secure=_secure_cookies())
    response.headers["Cache-Control"] = "no-store"
    return ApiResponse(code=0, message="ok", data={"logged_out": True})


@router.post("/logout-all", response_model=ApiResponse)
async def logout_all(
    response: Response,
    current_user: CurrentIdentity = Depends(get_current_user),
    ma_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: AsyncSession = Depends(get_db),
    service: SessionService = Depends(get_session_service),
):
    try:
        validate_csrf(ma_csrf, x_csrf_token)
    except SessionError as exc:
        raise _session_error(exc) from None
    await service.revoke_all(db, current_user.user_id, "logout_all")
    clear_session_cookies(response, secure=_secure_cookies())
    return ApiResponse(code=0, message="ok", data={"logged_out": True})


@router.get("/sessions", response_model=ApiResponse)
async def list_sessions(
    current_user: CurrentIdentity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.user_id == current_user.user_id)
            .order_by(AuthSession.last_seen_at.desc())
        )
    ).scalars().all()
    return ApiResponse(
        code=0,
        message="ok",
        data=[
            {
                "id": str(row.id),
                "active_role": row.active_role,
                "device_name": row.device_name,
                "ip_prefix": row.ip_prefix,
                "last_seen_at": row.last_seen_at.isoformat(),
                "expires_at": row.expires_at.isoformat(),
                "revoked": row.revoked_at is not None,
                "current": row.id == current_user.session_id,
            }
            for row in rows
        ],
    )


@router.delete("/sessions/{session_id}", response_model=ApiResponse)
async def revoke_session(
    session_id: uuid.UUID,
    current_user: CurrentIdentity = Depends(get_current_user),
    ma_csrf: str | None = Cookie(default=None),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: AsyncSession = Depends(get_db),
):
    try:
        validate_csrf(ma_csrf, x_csrf_token)
    except SessionError as exc:
        raise _session_error(exc) from None
    target = (
        await db.execute(
            select(AuthSession).where(
                AuthSession.id == session_id,
                AuthSession.user_id == current_user.user_id,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={"code": 40401, "error_key": "AUTH_SESSION_NOT_FOUND", "message": "会话不存在"},
        )
    if target.revoked_at is None:
        target.revoked_at = datetime.now(UTC)
        target.revoke_reason = "device_revoked"
    return ApiResponse(code=0, message="ok", data={"revoked": True})
