"""Public identity endpoints introduced by the unified auth contract."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.domains.identity.challenges import ChallengeError, ChallengeService, RedisChallengeStore
from app.domains.identity.sms import DemoSmsProvider, TencentSmsProvider
from app.gateway.redis import get_redis
from app.gateway.schemas import ApiResponse

router = APIRouter()


class SmsChallengeRequest(BaseModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    purpose: str


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
