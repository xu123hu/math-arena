"""Identity application services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.security import PasswordHasher
from app.models.identity import AuthSession, UserConsent, UserCredential
from app.models.role_binding import RoleBinding
from app.models.student_profile import StudentProfile
from app.models.user import User


class PasswordAuthenticationError(Exception):
    def __init__(self, error_key: str = "AUTH_PASSWORD_INVALID"):
        super().__init__("手机号或密码错误")
        self.error_key = error_key
        self.message = "手机号或密码错误"


class PasswordService:
    lock_after_failures = 5
    lock_duration = timedelta(minutes=15)

    def __init__(self, hasher: PasswordHasher | None = None):
        self.hasher = hasher or PasswordHasher()

    async def set_password(self, db: AsyncSession, user_id: uuid.UUID, password: str) -> None:
        secret_hash = self.hasher.hash(password)
        credential = (
            await db.execute(
                select(UserCredential).where(
                    UserCredential.user_id == user_id,
                    UserCredential.credential_type == "password",
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if credential is None:
            credential = UserCredential(
                user_id=user_id,
                credential_type="password",
                secret_hash=secret_hash,
                password_changed_at=now,
            )
            db.add(credential)
        else:
            credential.secret_hash = secret_hash
            credential.password_changed_at = now
            credential.failed_attempts = 0
            credential.locked_until = None
        await db.flush()

    async def authenticate(self, db: AsyncSession, phone: str | None, password: str) -> User:
        now = datetime.now(UTC)
        row = (
            await db.execute(
                select(User, UserCredential)
                .join(UserCredential, UserCredential.user_id == User.id)
                .where(
                    User.phone == phone,
                    User.deleted_at.is_(None),
                    UserCredential.credential_type == "password",
                )
            )
        ).one_or_none()
        if row is None:
            raise PasswordAuthenticationError()
        user, credential = row
        if user.status != "active":
            raise PasswordAuthenticationError("AUTH_ACCOUNT_RESTRICTED")
        if credential.locked_until is not None and credential.locked_until > now:
            raise PasswordAuthenticationError("AUTH_PASSWORD_LOCKED")
        check = self.hasher.verify_and_rehash(password, credential.secret_hash)
        if not check.valid:
            credential.failed_attempts += 1
            if credential.failed_attempts >= self.lock_after_failures:
                credential.locked_until = now + self.lock_duration
            await db.flush()
            raise PasswordAuthenticationError()
        credential.failed_attempts = 0
        credential.locked_until = None
        if check.replacement_hash:
            credential.secret_hash = check.replacement_hash
        await db.flush()
        return user

    async def reset_password(self, db: AsyncSession, user_id: uuid.UUID, password: str) -> None:
        user = (
            await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if user is None:
            raise PasswordAuthenticationError()
        await self.set_password(db, user_id, password)
        user.security_version += 1
        now = datetime.now(UTC)
        await db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now, revoke_reason="password_reset")
        )
        await db.flush()


class IdentityService:
    """Transaction-safe identity creation and student onboarding."""

    async def login_sms(self, db: AsyncSession, phone: str) -> tuple[User, bool]:
        now = datetime.now(UTC)
        created_id = await db.scalar(
            insert(User)
            .values(
                phone=phone,
                nickname="",
                status="active",
                onboarding_status="required",
                security_version=1,
                phone_verified_at=now,
            )
            .on_conflict_do_nothing(index_elements=[User.phone])
            .returning(User.id)
        )
        user = (
            await db.execute(select(User).where(User.phone == phone, User.deleted_at.is_(None)))
        ).scalar_one_or_none()
        if user is None or user.status != "active":
            raise PasswordAuthenticationError("AUTH_ACCOUNT_RESTRICTED")
        user.phone_verified_at = now
        await db.execute(
            insert(RoleBinding)
            .values(
                user_id=user.id,
                role="student",
                status="approved",
                _legacy_verified=True,
                approved_at=now,
            )
            .on_conflict_do_nothing(index_elements=[RoleBinding.user_id, RoleBinding.role])
        )
        await db.flush()
        return user, created_id is not None

    async def onboard_student(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        nickname: str,
        stage: str,
        grade: str,
        school: str | None,
        consent_version: str,
    ) -> User:
        user = (
            await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
        ).scalar_one()
        binding = (
            await db.execute(
                select(RoleBinding).where(
                    RoleBinding.user_id == user_id,
                    RoleBinding.role == "student",
                    RoleBinding.status == "approved",
                    RoleBinding.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        profile = (
            await db.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
        ).scalar_one_or_none()
        if profile is None:
            profile = StudentProfile(user_id=user_id)
            db.add(profile)
        profile.school_stage = stage
        profile.grade = grade
        binding.org_name = school or None
        user.nickname = nickname.strip()
        user.onboarding_status = "completed"
        await db.execute(
            insert(UserConsent)
            .values(
                user_id=user_id,
                consent_type="platform_terms",
                consent_version=consent_version,
                consented_at=datetime.now(UTC),
                source="student_onboarding",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    UserConsent.user_id,
                    UserConsent.consent_type,
                    UserConsent.consent_version,
                ]
            )
        )
        await db.flush()
        return user
