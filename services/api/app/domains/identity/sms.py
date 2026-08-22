"""SMS provider boundary and stable provider error mapping."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


class ProviderError(Exception):
    def __init__(self, error_key: str, message: str):
        super().__init__(message)
        self.error_key = error_key
        self.message = message


@dataclass(frozen=True)
class ProviderReceipt:
    provider: str
    external_id: str | None = None
    demo_code: str | None = None


class DemoSmsProvider:
    def __init__(self, *, environment: str, allowlist: set[str]):
        self.environment = environment
        self.allowlist = allowlist

    async def send(self, phone: str, purpose: str, code: str) -> ProviderReceipt:
        if self.environment == "production":
            raise ProviderError("SMS_PROVIDER_UNAVAILABLE", "生产环境未配置短信服务")
        if phone not in self.allowlist:
            raise ProviderError("SMS_DEMO_PHONE_NOT_ALLOWED", "该手机号不在演示短信白名单")
        return ProviderReceipt(provider="demo", demo_code=code)


def map_tencent_error(vendor_code: str) -> str:
    if "LimitExceeded" in vendor_code:
        return "SMS_RATE_LIMITED"
    if "Signature" in vendor_code or "Template" in vendor_code:
        return "SMS_TEMPLATE_UNAVAILABLE"
    if "Unauthorized" in vendor_code or "AuthFailure" in vendor_code:
        return "SMS_PROVIDER_AUTH_FAILED"
    if "InternalError" in vendor_code or "RequestTimeout" in vendor_code:
        return "SMS_PROVIDER_TEMPORARY_FAILURE"
    return "SMS_PROVIDER_FAILURE"


class TencentSmsProvider:
    """SDK-independent Tencent boundary.

    Deployment wiring supplies a sender that calls the approved Tencent SDK.
    Keeping that callable outside the domain makes credentials and SDK error
    objects impossible to leak into authentication services.
    """

    def __init__(
        self,
        *,
        sender: Callable[[str, str, str], Awaitable[str | None]] | None = None,
    ):
        self.sender = sender

    async def send(self, phone: str, purpose: str, code: str) -> ProviderReceipt:
        if self.sender is None:
            raise ProviderError("SMS_PROVIDER_UNAVAILABLE", "腾讯云短信尚未配置")
        try:
            external_id = await self.sender(phone, purpose, code)
        except Exception as exc:
            vendor_code = str(exc)
            raise ProviderError(map_tencent_error(vendor_code), "短信发送失败") from None
        return ProviderReceipt(provider="tencent", external_id=external_id)
