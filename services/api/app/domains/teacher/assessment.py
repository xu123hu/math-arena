"""M3 教师端：题集与作业（§12）。

- 生成结果先成为 quiz_set draft Artifact（复用 M2 题库供给 + 规范化去重 + 数量护栏）；
- 题量不足明确失败，不用重复题凑数；
- 教师确认 quiz_set 后才能据此创建 Assignment draft（默认 draft，不直接发布）；
- Assignment publish 单独确认、幂等、记录 teacher_action；不破坏 M2 published 兼容。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.artifacts import create_artifact, get_owned_artifact
from app.domains.teacher.scope import assert_teacher_in_class, raise_http
from app.models.coursework import Assignment, Quiz, QuizItem
from app.models.teacher import TeacherAction, TeachingArtifact
from app.skills.question_supply import supply_questions

ERR_NOT_FOUND = 40400
ERR_VALIDATION = 40001
ERR_CONFIRMATION_REQUIRED = 42210
ERR_DUPLICATE = 40902

TYPE_MAP = {"choice": "choice", "blank": "blank", "text": "solution"}


def _norm_question_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256("".join(text.split()).encode("utf-8")).hexdigest()[:16]


async def generate_quiz(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    knowledge_points: list[str],
    count: int,
    question_types: dict[str, int],
    difficulty: dict[str, float] | None,
    exclude_hashes: list[str],
    client_request_id: str,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)

    # 收集每题型目标数量（现有 supply 未按题型配比严格切分，做一次确定性分配与去重）
    wanted: list[tuple[str, int]] = [
        (qtype, max(0, int(question_types.get(qtype) or 0)))
        for qtype in ("choice", "blank", "text")
    ]
    target = sum(n for _, n in wanted)
    if target <= 0:
        target = count
        wanted = [("choice", max(1, count))]

    used_hashes: set[str] = set(exclude_hashes)
    items: list[dict[str, Any]] = []
    for qtype, n in wanted:
        if n <= 0:
            continue
        rows = await supply_questions(
            db,
            kp_codes=knowledge_points or [],
            q_type=qtype if qtype != "text" else "solution",
            difficulty=None,
            count=n,
            exclude_hashes=used_hashes,
            scope="student",
        )
        for row in rows:
            if row.hash in used_hashes:
                continue  # 去重
            used_hashes.add(row.hash)
            items.append(
                {
                    "item_no": len(items) + 1,
                    "q_type": TYPE_MAP.get(qtype, qtype),
                    "question_text": row.stem,
                    "options": row.options if isinstance(row.options, dict) else None,
                    "answer": row.answer,
                    "analysis": row.analysis,
                    "kp_code": row.kp_codes[0] if row.kp_codes else None,
                    "difficulty": row.difficulty,
                    "hash": row.hash,
                    "source": row.source,
                    "source_ref": f"qb:{row.id}",
                }
            )

    if len(items) < target:
        raise_http(
            ERR_VALIDATION,
            status.HTTP_400_BAD_REQUEST,
            "insufficient_questions",
            requested=target,
            available=len(items),
            recoverable=True,
        )

    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="quiz_set",
        scene="teacher.assessment",
        class_id=class_id,
        payload={
            "knowledge_points": knowledge_points,
            "difficulty": difficulty,
            "items": items,
            "question_type_distribution": question_types,
        },
        source_refs=[i["source_ref"] for i in items],
        engine="local",
        degraded=False,
        validation={"question_count": len(items), "dedup": True},
    )
    db.add(artifact)
    await db.flush()
    return {"artifact_id": str(artifact.id), "status": artifact.status, "question_count": len(items)}


async def _materialize_quiz(
    db: AsyncSession, teacher_id: uuid.UUID, artifact: TeachingArtifact
) -> uuid.UUID:
    """从已确认 quiz_set artifact 物化 Quiz + QuizItems，返回 quiz_id。"""
    payload = artifact.payload or {}
    quiz = Quiz(
        user_id=teacher_id,
        source="assignment",
        title=f"quiz_set-{artifact.id}",
        kp_codes=list(payload.get("knowledge_points") or []),
        status="active",
    )
    db.add(quiz)
    await db.flush()
    for it in payload.get("items") or []:
        db.add(
            QuizItem(
                quiz_id=quiz.id,
                item_no=it.get("item_no", 0),
                q_type=it.get("q_type", "choice"),
                question_text=it.get("question_text", ""),
                options=it.get("options"),
                answer=it.get("answer", ""),
                answer_analysis=it.get("analysis"),
                kp_code=it.get("kp_code"),
                difficulty=it.get("difficulty", "medium"),
                ai_generated=False,
                source=it.get("source"),
            )
        )
    await db.flush()
    return quiz.id


async def create_assignment(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    title: str,
    artifact_id: uuid.UUID,
    client_assignment_id: str,
    deadline: str | None,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)

    # 幂等：同 client_assignment_id 已创建 → 返回既有 draft
    existing = (
        await db.execute(
            select(Assignment).where(
                Assignment.creator_id == teacher_id,
                Assignment.client_assignment_id == client_assignment_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"assignment_id": str(existing.id), "status": existing.status, "replayed": True}

    artifact = await get_owned_artifact(db, teacher_id, artifact_id)
    if artifact.artifact_type != "quiz_set":
        raise_http(ERR_VALIDATION, 422, "artifact_not_quiz_set", recoverable=False)
    if artifact.status != "confirmed":
        raise_http(ERR_CONFIRMATION_REQUIRED, 422, "confirmation_required", recoverable=True)

    quiz_id = await _materialize_quiz(db, teacher_id, artifact)
    a = Assignment(
        class_id=class_id,
        creator_id=teacher_id,
        title=title,
        type="quiz",
        quiz_id=quiz_id,
        deadline=_parse_dt(deadline),
        status="draft",  # 新建教师作业默认 draft，不直接发布
        client_assignment_id=client_assignment_id,
        source_artifact_id=artifact_id,
    )
    db.add(a)
    await db.flush()
    return {"assignment_id": str(a.id), "status": a.status, "replayed": False}


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _get_assignment_in_class(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID, assignment_id: uuid.UUID
) -> Assignment:
    await assert_teacher_in_class(db, teacher_id, class_id)
    a = await db.get(Assignment, assignment_id)
    if a is None or a.deleted_at is not None or a.class_id != class_id:
        raise_http(ERR_NOT_FOUND, status.HTTP_404_NOT_FOUND, "not_found", recoverable=False)
    return a


async def _assignment_transition(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    target: str,
    required: str,
    client_request_id: str,
    idempotency_key: str | None,
    request_id: str | None,
) -> dict:
    a = await _get_assignment_in_class(db, teacher_id, class_id, assignment_id)
    if idempotency_key:
        existing = (
            await db.execute(
                select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"assignment_id": str(a.id), "status": a.status, "replayed": True}
    if a.status != required:
        # 已是目标状态 → 幂等成功
        if a.status == target:
            return {"assignment_id": str(a.id), "status": a.status, "replayed": True}
        raise_http(ERR_VALIDATION, 422, "invalid_state", current=a.status, recoverable=True)
    a.status = target
    db.add(
        TeacherAction(
            teacher_id=teacher_id,
            class_id=class_id,
            artifact_id=a.source_artifact_id,
            action_type=f"assignment.{target}",
            client_request_id=client_request_id,
            idempotency_key=idempotency_key,
            before_digest=None,
            after_digest=None,
            request_id=request_id,
            details={"assignment_id": str(a.id)},
        )
    )
    await db.flush()
    return {"assignment_id": str(a.id), "status": target, "replayed": False}


async def publish_assignment(
    db, teacher_id, class_id, assignment_id, *, client_request_id, idempotency_key, request_id
) -> dict:
    return await _assignment_transition(
        db, teacher_id, class_id, assignment_id,
        target="published", required="draft",
        client_request_id=client_request_id, idempotency_key=idempotency_key, request_id=request_id,
    )


async def close_assignment(
    db, teacher_id, class_id, assignment_id, *, client_request_id, idempotency_key, request_id
) -> dict:
    return await _assignment_transition(
        db, teacher_id, class_id, assignment_id,
        target="closed", required="published",
        client_request_id=client_request_id, idempotency_key=idempotency_key, request_id=request_id,
    )


async def archive_assignment(
    db, teacher_id, class_id, assignment_id, *, client_request_id, idempotency_key, request_id
) -> dict:
    a = await _get_assignment_in_class(db, teacher_id, class_id, assignment_id)
    if idempotency_key:
        existing = (
            await db.execute(
                select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"assignment_id": str(a.id), "status": a.status, "replayed": True}
    a.status = "archived"
    await db.flush()
    return {"assignment_id": str(a.id), "status": "archived", "replayed": False}


async def list_assignments(
    db, teacher_id: uuid.UUID, class_id: uuid.UUID | None, assignment_status: str | None
) -> list[dict]:
    from app.domains.teacher.today import teacher_class_ids

    class_ids = [class_id] if class_id else await teacher_class_ids(db, teacher_id)
    if not class_ids:
        return []
    stmt = (
        select(Assignment)
        .where(Assignment.class_id.in_(class_ids), Assignment.deleted_at.is_(None))
        .order_by(Assignment.created_at.desc())
    )
    if assignment_status:
        stmt = stmt.where(Assignment.status == assignment_status)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "assignment_id": str(a.id),
            "class_id": str(a.class_id),
            "title": a.title,
            "type": a.type,
            "status": a.status,
            "deadline": a.deadline.isoformat() if a.deadline else None,
        }
        for a in rows
    ]
