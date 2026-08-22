"""Password policy, Argon2id credentials, and security-version behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.domains.identity.router import get_challenge_service
from app.domains.identity.security import PasswordHasher, PasswordPolicyError
from app.domains.identity.service import PasswordService
from app.gateway.jwt import create_token_with_role
from app.main import app
from app.models.database import async_session_factory
from app.models.identity import AuthSession, UserCredential
from app.models.role_binding import RoleBinding
from app.models.user import User


@pytest.fixture(scope="module")
def password_hasher() -> PasswordHasher:
    return PasswordHasher()


@pytest.mark.parametrize("length", [1, 8, 14, 129])
def test_password_policy_rejects_out_of_range_lengths(password_hasher, length):
    with pytest.raises(PasswordPolicyError) as error:
        password_hasher.hash("数" * length)
    assert error.value.error_key == "AUTH_PASSWORD_POLICY"


@pytest.mark.parametrize("length", [15, 64, 128])
def test_password_policy_accepts_nist_length_boundaries(password_hasher, length):
    encoded = password_hasher.hash("数" * length)
    assert encoded.startswith("$argon2id$")
    assert password_hasher.verify_and_rehash("数" * length, encoded).valid is True


def test_password_policy_accepts_spaces_unicode_and_normalizes_nfc(password_hasher):
    composed = "é" * 14 + " pass phrase"
    decomposed = "e\u0301" * 14 + " pass phrase"
    encoded = password_hasher.hash(composed)

    assert password_hasher.verify_and_rehash(decomposed, encoded).valid is True


def test_password_policy_rejects_local_blocklist(password_hasher):
    with pytest.raises(PasswordPolicyError) as error:
        password_hasher.hash("password123456789")
    assert error.value.error_key == "AUTH_PASSWORD_BLOCKED"


def test_wrong_password_does_not_verify(password_hasher):
    encoded = password_hasher.hash("correct horse battery staple")
    assert password_hasher.verify_and_rehash("wrong password value", encoded).valid is False


@pytest.fixture
async def password_db():
    async with async_session_factory() as session:
        transaction = await session.begin()
        try:
            yield session
        finally:
            if transaction.is_active:
                await transaction.rollback()


async def _user_with_session(db):
    now = datetime.now(UTC)
    user = User(
        id=uuid.uuid4(),
        phone=f"137{uuid.uuid4().int % 100_000_000:08d}",
        nickname="password test",
        onboarding_status="completed",
    )
    db.add(user)
    await db.flush()
    db.add(RoleBinding(user_id=user.id, role="student", status="approved", verified=True))
    auth_session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_family_id=uuid.uuid4(),
        security_version=1,
        active_role="student",
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        expires_at=now + timedelta(days=7),
    )
    db.add(auth_session)
    await db.flush()
    return user, auth_session


async def test_set_and_authenticate_password_uses_credentials_table(password_db, password_hasher):
    user, _ = await _user_with_session(password_db)
    service = PasswordService(password_hasher)

    await service.set_password(password_db, user.id, "correct horse battery staple")
    authenticated = await service.authenticate(
        password_db, user.phone, "correct horse battery staple"
    )

    credential = (
        await password_db.execute(
            select(UserCredential).where(UserCredential.user_id == user.id)
        )
    ).scalar_one()
    assert credential.secret_hash.startswith("$argon2id$")
    assert authenticated.id == user.id
    assert user.password_hash is None


async def test_password_reset_increments_security_version_and_revokes_sessions(
    password_db, password_hasher
):
    user, auth_session = await _user_with_session(password_db)
    service = PasswordService(password_hasher)
    await service.set_password(password_db, user.id, "first secure password value")

    await service.reset_password(password_db, user.id, "second secure password value")
    await password_db.refresh(user)
    await password_db.refresh(auth_session)

    assert user.security_version == 2
    assert auth_session.revoked_at is not None
    assert auth_session.revoke_reason == "password_reset"
    authenticated = await service.authenticate(
        password_db, user.phone, "second secure password value"
    )
    assert authenticated.id == user.id


class AcceptingPasswordResetChallenge:
    async def consume(self, challenge_id: str, phone: str, purpose: str, code: str) -> None:
        if (
            challenge_id != "password-reset-challenge"
            or purpose != "password_reset"
            or code != "123456"
        ):
            raise AssertionError("password reset used the wrong challenge contract")


async def test_password_endpoints_set_login_and_reset(password_db):
    user, _ = await _user_with_session(password_db)
    await password_db.commit()
    token = create_token_with_role(str(user.id), "student")
    headers = {"Authorization": f"Bearer {token}"}
    app.dependency_overrides[get_challenge_service] = lambda: AcceptingPasswordResetChallenge()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            set_response = await client.post(
                "/api/auth/password/set",
                json={"password": "correct horse battery staple"},
                headers=headers,
            )
            assert set_response.status_code == 200
            assert set_response.json()["code"] == 0

            login_response = await client.post(
                "/api/auth/login/password",
                json={"phone": user.phone, "password": "correct horse battery staple"},
            )
            assert login_response.status_code == 200
            assert login_response.json()["data"]["access_token"]

            reset_response = await client.post(
                "/api/auth/password/reset",
                json={
                    "phone": user.phone,
                    "challenge_id": "password-reset-challenge",
                    "code": "123456",
                    "password": "second secure password value",
                },
            )
            assert reset_response.status_code == 200
            assert reset_response.json()["code"] == 0
    finally:
        app.dependency_overrides.pop(get_challenge_service, None)
