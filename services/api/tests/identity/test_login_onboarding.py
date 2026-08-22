"""SMS login and student onboarding contracts."""

from __future__ import annotations

import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domains.identity.router import get_challenge_service
from app.domains.identity.service import IdentityService
from app.main import app
from app.models.database import async_session_factory
from app.models.identity import UserConsent
from app.models.role_binding import RoleBinding
from app.models.student_profile import StudentProfile
from app.models.user import User


class AcceptingChallengeService:
    async def consume(self, challenge_id: str, phone: str, purpose: str, code: str):
        assert challenge_id == "challenge-login"
        assert purpose == "login"
        assert code == "123456"


async def _login(phone: str):
    app.dependency_overrides[get_challenge_service] = lambda: AcceptingChallengeService()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/api/auth/login/sms",
                json={
                    "phone": phone,
                    "challenge_id": "challenge-login",
                    "code": "123456",
                    "remember": False,
                },
            )
    finally:
        app.dependency_overrides.pop(get_challenge_service, None)


async def test_sms_login_atomically_creates_approved_student():
    phone = f"137{uuid.uuid4().int % 100_000_000:08d}"

    response = await _login(phone)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["expires_in"] == 900
    assert data["onboarding_required"] is True
    assert data["user"]["active_role"] == "student"
    assert data["user"]["roles"] == [
        {"role": "student", "status": "approved", "verified": True}
    ]
    assert any("ma_refresh=" in value for value in response.headers.get_list("set-cookie"))

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        bindings = (
            await db.execute(select(RoleBinding).where(RoleBinding.user_id == user.id))
        ).scalars().all()
        assert [(item.role, item.status) for item in bindings] == [("student", "approved")]


async def test_existing_sms_login_does_not_duplicate_identity():
    phone = f"138{uuid.uuid4().int % 100_000_000:08d}"
    first = await _login(phone)
    second = await _login(phone)

    assert first.status_code == second.status_code == 200
    assert first.json()["data"]["user"]["id"] == second.json()["data"]["user"]["id"]
    async with async_session_factory() as db:
        users = (await db.execute(select(User).where(User.phone == phone))).scalars().all()
        assert len(users) == 1


async def test_concurrent_student_registration_creates_one_identity():
    phone = f"136{uuid.uuid4().int % 100_000_000:08d}"

    async def register():
        async with async_session_factory() as db:
            user, created = await IdentityService().login_sms(db, phone)
            await db.commit()
            return user.id, created

    results = await asyncio.gather(register(), register())

    assert results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    async with async_session_factory() as db:
        assert len((await db.execute(select(User).where(User.phone == phone))).scalars().all()) == 1
        assert len(
            (
                await db.execute(
                    select(RoleBinding)
                    .join(User, User.id == RoleBinding.user_id)
                    .where(User.phone == phone, RoleBinding.role == "student")
                )
            ).scalars().all()
        ) == 1


async def test_student_onboarding_records_profile_and_consent():
    phone = f"139{uuid.uuid4().int % 100_000_000:08d}"
    login = await _login(phone)
    token = login.json()["data"]["access_token"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/identity/onboarding/student",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "nickname": "小数同学",
                "stage": "高中",
                "grade": "高二",
                "school": "示例中学",
                "consent_version": "2026-08-22",
            },
        )

    assert response.status_code == 200
    assert response.json()["data"]["onboarding_required"] is False
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == user.id))
        ).scalar_one()
        consent = (
            await db.execute(select(UserConsent).where(UserConsent.user_id == user.id))
        ).scalar_one()
        assert (user.nickname, user.onboarding_status) == ("小数同学", "completed")
        assert (profile.school_stage, profile.grade) == ("高中", "高二")
        assert consent.consent_version == "2026-08-22"
