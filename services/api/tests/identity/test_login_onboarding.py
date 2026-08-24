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
from app.models.identity import AuthSession, RoleApplication, UserConsent
from app.models.role_binding import RoleBinding
from app.models.student_profile import StudentProfile
from app.models.user import User


class AcceptingChallengeService:
    async def consume(self, challenge_id: str, phone: str, purpose: str, code: str):
        assert challenge_id == "challenge-login"
        assert purpose == "login"
        assert code == "123456"


class AcceptingRegistrationChallengeService:
    async def consume(self, challenge_id: str, phone: str, purpose: str, code: str):
        assert challenge_id == "registration"
        assert purpose == "registration"
        assert code == "123456"


async def _register(phone: str, **payload):
    app.dependency_overrides[get_challenge_service] = lambda: (
        AcceptingRegistrationChallengeService()
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                "/api/auth/register/sms",
                json={
                    "phone": phone,
                    "challenge_id": "registration",
                    "code": "123456",
                    "consent_version": "2026-08-24",
                    **payload,
                },
            )
    finally:
        app.dependency_overrides.pop(get_challenge_service, None)


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


async def test_student_sms_registration_requires_registration_challenge():
    phone = f"135{uuid.uuid4().int % 100_000_000:08d}"

    response = await _register(phone, role="student")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["active_role"] == "student"
    assert data["onboarding_required"] is True
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        consent = (
            await db.execute(select(UserConsent).where(UserConsent.user_id == user.id))
        ).scalar_one()
    assert (consent.consent_version, consent.source) == ("2026-08-24", "sms_registration")


async def test_teacher_sms_registration_creates_pending_application_not_teacher_session():
    phone = f"134{uuid.uuid4().int % 100_000_000:08d}"

    response = await _register(
        phone,
        role="teacher",
        organization_name="示例中学",
        teaching_stage="高中",
        subject="数学",
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["active_role"] == "student"
    assert data["pending_role"] == "teacher"
    assert data["identity_status"] == "pending_review"
    assert data["application"]["role"] == "teacher"
    assert data["application"]["status"] == "pending"
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        session = (
            await db.execute(
                select(AuthSession).where(
                    AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)
                )
            )
        ).scalar_one()
    assert (session.active_role, session.pending_role) == ("student", "teacher")


async def test_registration_rejects_login_purpose_challenge():
    from datetime import UTC, datetime

    from app.domains.identity.challenges import ChallengeService
    from app.domains.identity.sms import DemoSmsProvider
    from tests.identity.test_sms_challenges import InMemoryChallengeStore, _service

    phone = f"133{uuid.uuid4().int % 100_000_000:08d}"
    store = InMemoryChallengeStore(datetime(2026, 8, 24, tzinfo=UTC))
    challenge_service: ChallengeService = _service(
        store,
        DemoSmsProvider(environment="development", allowlist={phone}),
    )
    issued = await challenge_service.create(phone, "login", ip_prefix="127.0.0.0/24")
    app.dependency_overrides[get_challenge_service] = lambda: challenge_service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/auth/register/sms",
                json={
                    "phone": phone,
                    "challenge_id": issued.challenge_id,
                    "code": "123456",
                    "role": "student",
                    "consent_version": "2026-08-24",
                },
            )
    finally:
        app.dependency_overrides.pop(get_challenge_service, None)

    assert response.status_code == 400
    assert response.json()["error_key"] == "AUTH_CHALLENGE_PURPOSE_MISMATCH"


async def test_researcher_sms_registration_requires_research_direction():
    phone = f"132{uuid.uuid4().int % 100_000_000:08d}"

    response = await _register(phone, role="researcher", organization_name="示例大学")

    assert response.status_code == 422


async def test_professional_registration_resubmission_reuses_student_and_pending_application():
    phone = f"131{uuid.uuid4().int % 100_000_000:08d}"
    payload = {
        "role": "teacher",
        "organization_name": "示例中学",
        "teaching_stage": "高中",
        "subject": "数学",
    }

    first = await _register(phone, **payload)
    second = await _register(phone, **payload)

    assert first.status_code == second.status_code == 200
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        student_bindings = (
            (
                await db.execute(
                    select(RoleBinding).where(
                        RoleBinding.user_id == user.id, RoleBinding.role == "student"
                    )
                )
            )
            .scalars()
            .all()
        )
        applications = (
            (
                await db.execute(
                    select(RoleApplication).where(
                        RoleApplication.user_id == user.id, RoleApplication.role == "teacher"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(student_bindings) == 1
    assert len(applications) == 1


async def test_registration_rejects_an_already_approved_professional_role_without_mutation():
    phone = f"130{uuid.uuid4().int % 100_000_000:08d}"
    payload = {
        "role": "teacher",
        "organization_name": "示例中学",
        "teaching_stage": "高中",
        "subject": "数学",
    }
    created = await _register(phone, **payload)
    assert created.status_code == 200

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        application = (
            await db.execute(
                select(RoleApplication).where(
                    RoleApplication.user_id == user.id,
                    RoleApplication.role == "teacher",
                )
            )
        ).scalar_one()
        binding = (
            await db.execute(
                select(RoleBinding).where(
                    RoleBinding.user_id == user.id,
                    RoleBinding.role == "teacher",
                )
            )
        ).scalar_one()
        session = (
            await db.execute(select(AuthSession).where(AuthSession.user_id == user.id))
        ).scalar_one()
        application.status = "approved"
        binding.status = "approved"
        binding._legacy_verified = True
        await db.commit()
        state_before = (application.id, application.status, binding.status, session.id)

    rejected = await _register(phone, **payload)

    assert rejected.status_code == 409
    assert rejected.json()["error_key"] == "IDENTITY_ROLE_ALREADY_APPROVED"
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        application = (
            await db.execute(
                select(RoleApplication).where(
                    RoleApplication.user_id == user.id,
                    RoleApplication.role == "teacher",
                )
            )
        ).scalar_one()
        binding = (
            await db.execute(
                select(RoleBinding).where(
                    RoleBinding.user_id == user.id,
                    RoleBinding.role == "teacher",
                )
            )
        ).scalar_one()
        sessions = (
            await db.execute(select(AuthSession).where(AuthSession.user_id == user.id))
        ).scalars().all()
    assert (application.id, application.status, binding.status, sessions[0].id) == state_before
    assert len(sessions) == 1


async def test_registration_resubmission_surfaces_needs_more_info():
    phone = f"130{uuid.uuid4().int % 100_000_000:08d}"
    payload = {
        "role": "teacher",
        "organization_name": "示例中学",
        "teaching_stage": "高中",
        "subject": "数学",
    }
    created = await _register(phone, **payload)
    assert created.status_code == 200

    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        application = (
            await db.execute(
                select(RoleApplication).where(
                    RoleApplication.user_id == user.id,
                    RoleApplication.role == "teacher",
                )
            )
        ).scalar_one()
        application.status = "needs_more_info"
        await db.commit()

    response = await _register(phone, **payload)

    assert response.status_code == 200
    assert response.json()["data"]["identity_status"] == "needs_more_info"
    assert response.json()["data"]["application"]["status"] == "needs_more_info"


async def test_registration_rejects_whitespace_only_required_professional_values():
    teacher = await _register(
        f"130{uuid.uuid4().int % 100_000_000:08d}",
        role="teacher",
        organization_name="   ",
    )
    researcher = await _register(
        f"130{uuid.uuid4().int % 100_000_000:08d}",
        role="researcher",
        organization_name="示例大学",
        research_direction="   ",
    )

    assert teacher.status_code == 422
    assert researcher.status_code == 422


async def test_registration_normalizes_required_professional_values():
    phone = f"130{uuid.uuid4().int % 100_000_000:08d}"

    response = await _register(
        phone,
        role="researcher",
        organization_name="  示例大学  ",
        research_direction="  几何分析  ",
    )

    assert response.status_code == 200
    assert response.json()["data"]["application"]["organization_name"] == "示例大学"
    async with async_session_factory() as db:
        user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
        application = (
            await db.execute(select(RoleApplication).where(RoleApplication.user_id == user.id))
        ).scalar_one()
    assert application.research_direction == "几何分析"


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
