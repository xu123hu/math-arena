"""Phone-change and account-deletion lifecycle contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domains.identity.service import AccountLifecycleService
from app.domains.identity.sessions import SessionService
from app.models.database import async_session_factory
from app.models.identity import AccountDeletionRequest, AuthSession
from app.models.role_binding import RoleBinding
from app.models.user import User


async def _active_user(db):
    user = User(
        phone=f"137{uuid.uuid4().int % 100_000_000:08d}",
        email=f"{uuid.uuid4().hex}@example.test",
        nickname="待治理用户",
        onboarding_status="completed",
    )
    db.add(user)
    await db.flush()
    db.add(RoleBinding(user_id=user.id, role="student", status="approved", verified=True))
    await db.flush()
    return user


async def test_phone_change_rejects_bound_number_and_revokes_sessions():
    async with async_session_factory() as db:
        user = await _active_user(db)
        other = await _active_user(db)
        issued = await SessionService(refresh_pepper="lifecycle-pepper").issue(
            db, user, "student", remember=False
        )
        old_phone = user.phone
        new_phone = f"136{uuid.uuid4().int % 100_000_000:08d}"
        await db.commit()

    async with async_session_factory() as db:
        service = AccountLifecycleService()
        try:
            await service.change_phone(db, user.id, old_phone, other.phone)
        except Exception as exc:
            assert exc.error_key == "IDENTITY_PHONE_ALREADY_BOUND"
            await db.rollback()
        changed = await service.change_phone(db, user.id, old_phone, new_phone)
        await db.commit()
        assert changed.phone == new_phone

    async with async_session_factory() as db:
        stored = await db.get(User, user.id)
        session = await db.get(AuthSession, issued.session_id)
        assert stored.security_version == 2
        assert session.revoked_at is not None


async def test_deletion_cooling_cancel_and_execution_anonymizes_identity():
    now = datetime.now(UTC)
    async with async_session_factory() as db:
        user = await _active_user(db)
        old_phone = user.phone
        request = await AccountLifecycleService(now=lambda: now).request_deletion(db, user.id)
        await db.commit()
        assert request.execute_after == now + timedelta(days=7)

    async with async_session_factory() as db:
        user = await db.get(User, user.id)
        assert user.status == "deletion_pending"
        cancelled = await AccountLifecycleService(now=lambda: now).cancel_deletion(db, user.id)
        await db.commit()
        assert cancelled.status == "cancelled"

    async with async_session_factory() as db:
        request = await AccountLifecycleService(now=lambda: now).request_deletion(db, user.id)
        request.execute_after = now - timedelta(seconds=1)
        await db.commit()

    async with async_session_factory() as db:
        count = await AccountLifecycleService(now=lambda: now).execute_due_deletions(db)
        await db.commit()
        assert count == 1
        stored = await db.get(User, user.id)
        deletion = await db.scalar(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.user_id == user.id,
                AccountDeletionRequest.status == "completed",
            )
        )
        assert stored.phone is None
        assert stored.email is None
        assert stored.nickname == ""
        assert stored.deleted_at is not None
        assert deletion.result_digest

    async with async_session_factory() as db:
        fresh = User(phone=old_phone, nickname="新账号")
        db.add(fresh)
        await db.commit()
        assert fresh.id != user.id
