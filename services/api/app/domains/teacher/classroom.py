"""M3 教师端：课堂模式与视频/课堂洞察（§14）。

- 课堂模式状态由本地缓存持有，带 TTL、教师与 class scope；启停属于 WRITE，
  要求确认与审计（写 teacher_action，幂等）。
- 视频数据未接入时返回空洞察与 degraded=true，不得伪造参与度。
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.scope import assert_teacher_in_class
from app.models.teacher import TeacherAction

ERR_NOT_FOUND = 40400
# 课堂模式 TTL（秒）
CLASSROOM_TTL_S = 4 * 3600

# 进程内课堂状态缓存：key=class_id -> {"enabled", "lesson_id", "teacher_id",
# "expires_at", "updated_at"}。真实部署可换 Redis；本实现保持幂等语义与审计一致。
_CLASSROOM_STATE: dict[str, dict] = {}


def _now_ts() -> float:
    return time.time()


async def set_classroom_mode(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    enabled: bool,
    lesson_id: uuid.UUID | None,
    duration_minutes: int | None,
    client_request_id: str,
    idempotency_key: str | None,
    request_id: str | None,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)

    key = str(class_id)
    cached = _CLASSROOM_STATE.get(key)
    if (
        cached
        and cached.get("expires_at")
        and cached["expires_at"] > _now_ts()
        and cached.get("enabled") == enabled
        and cached.get("lesson_id") == (str(lesson_id) if lesson_id else None)
    ):
        # 幂等重放：状态一致则直接返回
        return {"class_id": str(class_id), "enabled": cached["enabled"], "replayed": True}

    # 确认 + 幂等键审计
    if idempotency_key:
        existing = (
            await db.execute(
                select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            prior = _CLASSROOM_STATE.get(key, {})
            return {
                "class_id": str(class_id),
                "enabled": prior.get("enabled", enabled),
                "replayed": True,
            }

    ttl = (duration_minutes * 60) if duration_minutes else CLASSROOM_TTL_S
    _CLASSROOM_STATE[key] = {
        "enabled": enabled,
        "lesson_id": str(lesson_id) if lesson_id else None,
        "teacher_id": str(teacher_id),
        "expires_at": _now_ts() + ttl,
        "updated_at": _now_ts(),
    }
    db.add(
        TeacherAction(
            teacher_id=teacher_id,
            class_id=class_id,
            artifact_id=lesson_id,
            action_type="classroom.mode.set",
            client_request_id=client_request_id,
            idempotency_key=idempotency_key,
            request_id=request_id,
            details={"enabled": enabled, "lesson_id": str(lesson_id) if lesson_id else None},
        )
    )
    await db.flush()
    return {"class_id": str(class_id), "enabled": enabled, "replayed": False}


async def classroom_state(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)
    st = _CLASSROOM_STATE.get(str(class_id))
    if st and st.get("expires_at") and st["expires_at"] <= _now_ts():
        st = None
    if st is None:
        return {"class_id": str(class_id), "enabled": False, "lesson_id": None}
    return {
        "class_id": str(class_id),
        "enabled": bool(st["enabled"]),
        "lesson_id": st.get("lesson_id"),
    }


async def video_insights(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID, *, lesson_id: uuid.UUID | None
) -> dict:
    """视频/课堂洞察：数据源未接入 → 空数据 + degraded=true，不伪造参与度。"""
    await assert_teacher_in_class(db, teacher_id, class_id)
    return {
        "class_id": str(class_id),
        "lesson_id": str(lesson_id) if lesson_id else None,
        "participation": {},
        "timeline_events": [],
        "actionable_recommendations": [],
        "degraded": True,
        "reason": "video_data_source_not_connected",
    }
