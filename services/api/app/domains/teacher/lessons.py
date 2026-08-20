"""M3 教师端：教案 / 课件 / 讲解（§5.3 F1/F2/F11）。

- 教案从"复用并适配"开始：本地确定性模板 + 已有材料 + 规则建议（engine=local）；
  星辰可用时经 capability_gateway 走 wf_lesson_plan，失败仍可本地降级；
- 成品均是 draft Artifact，确认前不产生正式业务影响；
- 应用洞察：只改/新增 draft 版本，不原地篡改已确认版本。
"""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.artifacts import (
    create_artifact,
    get_owned_artifact,
    update_artifact,
)
from app.domains.teacher.scope import assert_teacher_in_class, raise_http
from app.models.teacher import TeachingArtifact

ERR_NOT_FOUND = 40400

_DEFAULT_TIMELINE = [
    ("导入", "min", 5),
    ("探究", "min", 10),
    ("例题", "min", 12),
    ("学生练习", "min", 10),
    ("小结", "min", 5),
]


def _local_lesson_payload(topic: str, *, requirements: str | None, duration_minutes: int | None) -> dict:
    return {
        "topic": topic,
        "duration_minutes": duration_minutes or 45,
        "objectives": [f"掌握{topic}的核心概念与基本方法"],
        "timeline": [
            {"phase": name, "unit": unit, "minutes": mins}
            for name, unit, mins in _DEFAULT_TIMELINE
        ],
        "requirements": requirements,
        "template": "local_deterministic_template_v1",
        "insert_answer": [],
    }


async def adapt_lesson(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    topic: str,
    source_artifact_id: uuid.UUID | None,
    source_refs: list[str],
    requirements: str | None,
    duration_minutes: int | None,
    client_request_id: str,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)

    import app.domains.teacher.capability_gateway as gw

    # 星辰可接入时走 wf_lesson_plan；其失败/未配置均由本地模板降级
    result = await gw.run_capability(
        db,
        teacher_id,
        scene="teacher.prep",
        class_id=class_id,
        capability="adapt_lesson",
        payload={
            "topic": topic,
            "requirements": requirements,
            "duration_minutes": duration_minutes,
        },
    )

    payload = result.get("payload") or _local_lesson_payload(topic, requirements=requirements, duration_minutes=duration_minutes)

    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="lesson_plan",
        scene="teacher.prep",
        class_id=class_id,
        payload=payload,
        source_refs=source_refs,
        engine=result.get("engine", "local"),
        degraded=result.get("degraded", False),
        warnings=(result.get("warnings") or []) if not result.get("degraded") else result.get("warnings") or ["本地模板模式"],
        parent_artifact_id=source_artifact_id,
        validation=result.get("validation", {"kind": "local_template", "deterministic": True}),
    )
    db.add(artifact)
    await db.flush()
    return {"artifact_id": str(artifact.id), "status": artifact.status, "degraded": artifact.degraded}


async def create_lesson(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    title: str,
    topic: str | None,
    duration_minutes: int | None,
    content: dict,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)
    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="lesson_plan",
        scene="teacher.prep",
        class_id=class_id,
        payload={**content, "title": title, "topic": topic or title, "duration_minutes": duration_minutes},
        engine="local",
        degraded=False,
        validation={"kind": "manual", "deterministic": True},
    )
    db.add(artifact)
    await db.flush()
    return {"artifact_id": str(artifact.id), "status": artifact.status}


async def list_lessons(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID | None
) -> list[dict]:
    stmt = select(TeachingArtifact).where(
        TeachingArtifact.owner_id == teacher_id,
        TeachingArtifact.artifact_type == "lesson_plan",
        TeachingArtifact.deleted_at.is_(None),
    )
    if class_id:
        stmt = stmt.where(TeachingArtifact.class_id == class_id)
    rows = (await db.execute(stmt.order_by(TeachingArtifact.updated_at.desc()))).scalars().all()
    return [
        {
            "lesson_id": str(a.id),
            "class_id": str(a.class_id) if a.class_id else None,
            "status": a.status,
            "version": a.version,
            "title": (a.payload or {}).get("title") or (a.payload or {}).get("topic"),
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in rows
    ]


async def get_lesson(
    db: AsyncSession, teacher_id: uuid.UUID, lesson_id: uuid.UUID
) -> dict:
    a = await get_owned_artifact(db, teacher_id, lesson_id)
    if a.artifact_type != "lesson_plan":
        raise_http(ERR_NOT_FOUND, status.HTTP_404_NOT_FOUND, "not_found", recoverable=False)
    return {
        "lesson_id": str(a.id),
        "status": a.status,
        "version": a.version,
        "content": a.payload,
        "degraded": a.degraded,
        "engine": a.engine,
        "warnings": a.warnings or [],
    }


async def create_slides(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    lesson_id: uuid.UUID,
    *,
    version: int,
    style: str | None,
    requirements: str | None,
) -> dict:
    lesson = await get_owned_artifact(db, teacher_id, lesson_id)
    # slides 是可发布产物：基于已确认教案生成 slide_deck draft
    if lesson.status == "draft":
        raise_http(42210, 422, "confirmation_required", recoverable=True)
    payload = {
        "slides": _outline_from_lesson(lesson),
        "style": style or "课堂模板",
        "requirements": requirements,
    }
    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="slide_deck",
        scene="teacher.prep",
        class_id=lesson.class_id,
        payload=payload,
        source_refs=[f"artifact:{lesson_id}"],
        engine="local",
        degraded=False,
        parent_artifact_id=lesson_id,
        validation={"kind": "outline", "deterministic": True},
    )
    db.add(artifact)
    await db.flush()
    return {"artifact_id": str(artifact.id), "status": artifact.status, "outline": payload["slides"]}


def _outline_from_lesson(lesson: TeachingArtifact) -> list[dict]:
    timeline = (lesson.payload or {}).get("timeline") or []
    return [
        {"page": i + 1, "title": p.get("phase", f"第{i+1}页"), "bullets": [],
         "notes": f"约{p.get('minutes', '')}分钟"}
        for i, p in enumerate(timeline)
    ] or [{"page": 1, "title": "课堂", "bullets": [], "notes": ""}]


async def create_explainer(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    *,
    question: str,
    reference_solution: str | None,
    target_minutes: int | None,
) -> dict:
    await assert_teacher_in_class(db, teacher_id, class_id)
    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="explanation",
        scene="teacher.prep",
        class_id=class_id,
        payload={
            "question": question,
            "reference_solution": reference_solution,
            "target_minutes": target_minutes,
            "steps": _explanatory_steps(question),
        },
        engine="local",
        degraded=False,
        validation={"kind": "deterministic", "verified": False},
    )
    db.add(artifact)
    await db.flush()
    return {"artifact_id": str(artifact.id), "status": artifact.status}


def _explanatory_steps(question: str) -> list[dict]:
    return [
        {"step": 1, "instruction": "重述问题与关键条件", "detail": question, "is_certain": True},
        {"step": 2, "instruction": "给出分步推导方向", "detail": "需结合标准答案与教师材料", "is_certain": False},
        {"step": 3, "instruction": "易错点提醒", "detail": "待教师依据本班错因补充", "is_certain": False},
    ]


async def apply_insight_to_lesson(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    lesson_id: uuid.UUID,
    *,
    insight_summary: str,
    version: int,
    instruction: str | None,
) -> dict:
    lesson = await get_owned_artifact(db, teacher_id, lesson_id)
    new_content = dict(lesson.payload or {})
    new_content["insert_answer"] = list(new_content.get("insert_answer", [])) + [
        {"kind": "insight", "summary": insight_summary, "instruction": instruction}
    ]
    if lesson.status == "draft":
        # 草稿直接基于 version 就地更新（乐观锁）
        updated, _created = await update_artifact(
            db, teacher_id, lesson_id, version=version, payload=new_content
        )
    else:
        updated, _created = await update_artifact(
            db, teacher_id, lesson_id, version=version, payload=new_content
        )
    await db.flush()
    return {"lesson_id": str(updated.id), "status": updated.status, "version": updated.version}
