"""M3 教师端：题集与作业（§12）。

- 生成结果先成为 quiz_set draft Artifact（复用 M2 题库供给 + 规范化去重 + 数量护栏）；
- 题库不足时用明确标注的本地确定性模板补齐，不重复题、不伪装真题；
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

from app.domains.teacher.artifacts import (
    _serialize_artifact,
    create_artifact,
    get_owned_artifact,
)
from app.domains.teacher.scope import assert_teacher_in_class, raise_http
from app.models.coursework import Assignment, AssignmentTarget, Quiz, QuizItem
from app.models.teacher import TeacherAction, TeachingArtifact
from app.skills.question_supply import supply_questions

ERR_NOT_FOUND = 40400
ERR_VALIDATION = 40001
ERR_CONFIRMATION_REQUIRED = 42210
ERR_DUPLICATE = 40902

TYPE_MAP = {"choice": "choice", "blank": "blank", "text": "solution"}


def _local_fallback_item(qtype: str, item_no: int, kp_code: str | None) -> dict[str, Any]:
    variant = item_no
    if qtype == "choice":
        answer_value = variant + 2
        question = f"方程 x + {variant} = {answer_value} 的解是（ ）。"
        options = {"A": "1", "B": "2", "C": "3", "D": "4"}
        answer = "B"
        analysis = f"两边同时减去 {variant}，得到 x=2。"
    elif qtype == "blank":
        coefficient = variant + 1
        question = f"函数 f(x)={coefficient}x² 的导数 f'(x)=____。"
        options = None
        answer = f"{2 * coefficient}x"
        analysis = "使用幂函数求导公式 (x^n)'=nx^(n-1)。"
    else:
        root_a, root_b = variant + 1, variant + 2
        question = f"解方程 (x-{root_a})(x-{root_b})=0，并写出主要步骤。"
        options = None
        answer = f"x={root_a} 或 x={root_b}"
        analysis = "由零乘积性质，两个因式分别等于 0。"
    return {
        "item_no": item_no,
        "q_type": TYPE_MAP.get(qtype, qtype),
        "question_text": question,
        "options": options,
        "answer": answer,
        "analysis": analysis,
        "kp_code": kp_code,
        "difficulty": "easy" if qtype != "text" else "medium",
        "hash": _norm_question_hash(f"local:{qtype}:{item_no}:{question}"),
        "source": "local_template",
        "source_ref": None,
    }


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
    fallback_count = 0
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
        type_added = 0
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
                    "analysis": row.analysis or "题库未提供解析，请教师确认后补充。",
                    "kp_code": row.kp_codes[0] if row.kp_codes else None,
                    "difficulty": row.difficulty,
                    "hash": row.hash,
                    "source": row.source,
                    "source_ref": f"qb:{row.id}",
                }
            )
            type_added += 1

        for _ in range(max(0, n - type_added)):
            items.append(
                _local_fallback_item(
                    qtype,
                    len(items) + 1,
                    knowledge_points[0] if knowledge_points else None,
                )
            )
            fallback_count += 1

    items = items[:target]

    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="quiz_set",
        scene="teacher.assessment",
        class_id=class_id,
        payload={
            "knowledge_points": knowledge_points,
            "count": target,
            "difficulty": difficulty,
            "items": items,
            "duplicated": 0,
            "insufficient": False,
            "question_type_distribution": question_types,
        },
        source_refs=[i["source_ref"] for i in items if i.get("source_ref")],
        engine="local",
        degraded=fallback_count > 0,
        warnings=[f"题库不足，已用本地模板补齐 {fallback_count} 题"] if fallback_count else [],
        validation={
            "question_count": len(items),
            "dedup": True,
            "bank_count": len(items) - fallback_count,
            "fallback_count": fallback_count,
        },
    )
    db.add(artifact)
    await db.flush()
    # 对齐前端 TeacherArtifact：返回完整 Artifact（content 含题集）
    return _serialize_artifact(artifact)


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


def _serialize_assignment(a: Assignment) -> dict:
    """对齐前端 Assignment 契约。"""
    return {
        "assignment_id": str(a.id),
        "client_assignment_id": a.client_assignment_id,
        "class_id": str(a.class_id),
        "title": a.title,
        "type": a.type,
        "status": a.status,
        "deadline": a.deadline.isoformat() if a.deadline else None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


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
        data = _serialize_assignment(existing)
        data["replayed"] = True
        return data

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
    # 班级定向：学生端 /api/student/assignments 依赖 assignment_targets
    # （target_type=class）；发布前为 draft，学生仍不可见（查询过滤 status=published）
    db.add(AssignmentTarget(assignment_id=a.id, target_type="class", target_id=class_id))
    await db.flush()
    data = _serialize_assignment(a)
    data["replayed"] = False
    return data


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
            data = _serialize_assignment(a)
            data["replayed"] = True
            return data
    if a.status != required:
        # 已是目标状态 → 幂等成功
        if a.status == target:
            data = _serialize_assignment(a)
            data["replayed"] = True
            return data
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
    data = _serialize_assignment(a)
    data["replayed"] = False
    return data


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
            data = _serialize_assignment(a)
            data["replayed"] = True
            return data
    a.status = "archived"
    await db.flush()
    data = _serialize_assignment(a)
    data["replayed"] = False
    return data


async def list_assignments(
    db, teacher_id: uuid.UUID, class_id: uuid.UUID | None, assignment_status: str | None
) -> list[dict]:
    from app.domains.teacher.today import teacher_class_ids

    if class_id is not None:
        await assert_teacher_in_class(db, teacher_id, class_id)
        class_ids = [class_id]
    else:
        class_ids = await teacher_class_ids(db, teacher_id)
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
    return [_serialize_assignment(a) for a in rows]
