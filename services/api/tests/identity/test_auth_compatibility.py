"""Compatibility-window authentication contracts."""

from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.main import app
from app.models.database import async_session_factory
from app.models.user import User


async def test_class_code_login_is_deprecated_and_creates_no_user():
    nickname = f"legacy-{uuid.uuid4().hex[:10]}"
    async with async_session_factory() as db:
        before = await db.scalar(select(func.count()).select_from(User))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/auth/login-by-code",
            json={"invite_code": "ABCDEF", "nickname": nickname},
        )

    assert response.status_code == 410
    assert response.json()["error_key"] == "AUTH_CLASS_CODE_LOGIN_DEPRECATED"
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"]
    async with async_session_factory() as db:
        after = await db.scalar(select(func.count()).select_from(User))
    assert after == before


async def test_legacy_sms_endpoint_announces_compatibility_sunset():
    phone = f"135{uuid.uuid4().int % 100_000_000:08d}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/auth/sms-code", json={"phone": phone})

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Sunset"] == "Sat, 05 Sep 2026 00:00:00 GMT"
