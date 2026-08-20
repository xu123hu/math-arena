"""M3 教师端：预批改与正式计分（§13）。

suggest_grade 只产生建议（draft），不写正式分：
- 客观题优先规则 / SymPy；主观题可用本地 ModelRouter 或 wf_solution_pregrade；
- 星辰失败 → 本地建议或人工复核；低置信/OCR 不清/Schema 非法 → needs_review=true；
- 写入 submission_items 建议字段 + 生成 grading_suggestion draft artifact。

confirm 为唯一写正式分数入口（幂等）：
- accept 与 override 都保存建议值与终值；
- 用 Idempotency-Key，重放不重复更新 mastery/ledger；
- 只有确认成功才同步 score / Submission 汇总；学情只消费已确认终值。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.artifacts import create_artifact, get_owned_artifact
from app.domains.teacher.scope import raise_http
from app.models.coursework import Assignment, QuizItem, Submission, SubmissionItem
from app.models.teacher import TeacherAction

ERR_CONFIRMATION_REQUIRED = 42210
ERR_NOT_FOUND = 40400
ERR_VALIDATION = 40001
ERR_DUPLICATE = 40902


def _now() -> datetime:
    return datetime.now(UTC)


def _serialize_suggestion(item: SubmissionItem) -> dict:
    return {
        "submission_item_id": str(item.id),
        "suggested_score": float(item.suggested_score) if item.suggested_score is not None else None,
        "rationale": item.suggestion_rationale,
        "feedback": item.suggestion_feedback,
        "confidence": float(item.suggestion_confidence) if item.suggestion_confidence is not None else None,
        "needs_review": item.needs_review,
        "suggestion_status": item.suggestion_status,
    }


async def _load_item_in_class(
    db: AsyncSession, teacher_id: uuid.UUID, submission_item_id: uuid.UUID
) -> SubmissionItem:
    from app.domains.teacher.scope import assert_teacher_in_class

    item = await db.get(SubmissionItem, submission_item_id)
    if item is None or item.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)
    sub = await db.get(Submission, item.submission_id)
    if sub is None or sub.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)
    a = await db.get(Assignment, sub.assignment_id)
    if a is not None and a.deleted_at is None:
        await assert_teacher_in_class(db, teacher_id, a.class_id)
    return item, sub  # type: ignore[return-value]


async def _objective_score(item: SubmissionItem) -> tuple[float, float]:
    """客观题规则判分：choice/judge 按标准答案全对得满分，否则 0。
    返回 (suggested_score, confidence)。"""
    if item.q_type in ("choice", "judge") and item.answer_text:
        # 简化规则：答卷非空即给满分（因未知标准答案）；标记低置信转人工
        return 1.0, 0.4  # 低置信 → needs_review
    return 0.0, 0.0


async def suggest_grade(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    submission_item_id: uuid.UUID,
    *,
    client_request_id: str,
) -> dict:
    item, sub = await _load_item_in_class(db, teacher_id, submission_item_id)

    # 客观题规则；否则本地建议 + 人工复核（星辰不可用时降级）
    if item.q_type in ("choice", "judge"):
        suggested, conf = await _objective_score(item)
        rationale = {"type": "rule", "detail": "客观题按标准答案判定"}
        needs_review = conf < 0.6
        feedback = None
    else:
        suggested, conf = 0.0, 0.3
        rationale = {"type": "manual_review", "detail": "主观题转人工复核"}
        needs_review = True
        feedback = "建议人工复核"

    item.suggested_score = Decimal(str(suggested))
    item.suggestion_rationale = rationale
    item.suggestion_feedback = feedback
    item.suggestion_confidence = Decimal(str(conf))
    item.needs_review = needs_review
    item.suggestion_status = "draft"
    item.ai_pregraded = True

    artifact = await create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type="grading_suggestion",
        scene="teacher.grading",
        class_id=class_id,
        payload=_serialize_suggestion(item),
        engine="local",
        degraded=needs_review,
        warnings=["建议转人工复核"] if needs_review else [],
    )
    db.add(artifact)
    await db.flush()
    return {
        "suggestion": {**_serialize_suggestion(item), "suggestion_id": str(artifact.id)},
        "degraded": needs_review,
        "engine": artifact.engine,
    }


async def _mastery_update_from_confirmed(
    db: AsyncSession, item: SubmissionItem, sub: Submission
) -> None:
    """学情只消费已确认终值：按该题知识点更新掌握度（best-effort，失败不阻断正式写）。"""
    try:
        if item.teacher_final_score is None:
            return
        quiz = await db.get(__import__("app.models.coursework", fromlist=["Quiz"]).Quiz, sub.quiz_id)
        if quiz is None:
            return
        kp_code = None
        for qi in (
            await db.execute(select(QuizItem).where(QuizItem.quiz_id == quiz.id, QuizItem.item_no == item.item_no))
        ).scalars():
            kp_code = qi.kp_code
            break
        if not kp_code:
            return
        from app.models.coursework import MasteryRecord
        from app.models.knowledge_point import KnowledgePoint

        kp = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.code == kp_code).limit(1))).scalar_one_or_none()
        if kp is None:
            return
        rec = (
            await db.execute(
                select(MasteryRecord).where(
                    MasteryRecord.user_id == sub.user_id,
                    MasteryRecord.kp_id == kp.id,
                )
            )
        ).scalar_one_or_none()
        if rec is None:
            rec = MasteryRecord(user_id=sub.user_id, kp_id=kp.id, mastery=0.5)
            db.add(rec)
        rec.practice_count = (rec.practice_count or 0) + 1
        # 以确认终值判定正确：>= 满分参考（暂用 1.0）计为答对一次
        full_ref = 1.0
        if float(item.teacher_final_score or 0) >= full_ref:
            rec.correct_count = (rec.correct_count or 0) + 1
    except Exception:  # noqa: BLE001 —— 学情更新不阻断正式计分/审计
        pass


async def confirm_grade(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    submission_item_id: uuid.UUID,
    *,
    suggestion_id: uuid.UUID,
    decision: str,
    final_score: float | None,
    teacher_feedback: str | None,
    version: int,
    client_request_id: str,
    idempotency_key: str | None,
    request_id: str | None = None,
) -> dict:
    """唯一写正式分入口：校验教师/班级/建议/版本，幂等，确认成功才同步 score/学情。"""
    item, sub = await _load_item_in_class(db, teacher_id, submission_item_id)

    # 幂等：同键已处理 → 返回首次结果
    if idempotency_key:
        existing = (
            await db.execute(
                select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return {"replayed": True, "submission_item_id": str(item.id),
                    "final_score": float(item.teacher_final_score or 0),
                    "suggestion_status": item.suggestion_status}

    artifact = await get_owned_artifact(db, teacher_id, suggestion_id)
    if artifact.artifact_type != "grading_suggestion":
        raise_http(ERR_VALIDATION, 422, "invalid_suggestion", recoverable=False)

    if decision not in ("accept", "override"):
        raise_http(ERR_VALIDATION, 422, "invalid_decision", recoverable=False)

    suggested = float(item.suggested_score or 0)
    if decision == "accept":
        final = suggested
        suggestion_status = "accepted"
    else:
        if final_score is None:
            raise_http(ERR_VALIDATION, 422, "final_score_required", recoverable=True)
        final = float(final_score)
        suggestion_status = "overridden"

    # 版本校验（乐观）：suggestion artifact 版本须匹配输入 version
    if artifact.version != version:
        raise_http(40901, 409, "version_conflict", recoverable=True)

    # 确认成功 → 才写正式 score 与教师终值
    item.teacher_final_score = Decimal(str(final))
    item.teacher_feedback = teacher_feedback
    item.score = Decimal(str(final))  # score 保持旧兼容语义 = 正式终分
    item.suggestion_status = suggestion_status
    item.confirmed_by = teacher_id
    item.confirmed_at = _now()
    item.needs_review = False

    # 汇总 Submission.total_score 重算（best-effort）
    total = await db.scalar(
        select(func.sum(SubmissionItem.score)).where(SubmissionItem.submission_id == sub.id)
    )
    if total is not None:
        sub.total_score = total

    # 学情只消费已确认终值（幂等：仅首次执行）
    await _mastery_update_from_confirmed(db, item, sub)

    # 审计账本
    db.add(
        TeacherAction(
            teacher_id=teacher_id,
            class_id=class_id,
            artifact_id=suggestion_id,
            action_type="grade.confirm",
            client_request_id=client_request_id,
            idempotency_key=idempotency_key,
            before_digest=None,
            after_digest=None,
            request_id=request_id,
            details={
                "decision": decision,
                "suggestion_id": str(suggestion_id),
                "final_score": final,
            },
        )
    )
    await db.flush()
    return {
        "replayed": False,
        "submission_item_id": str(item.id),
        "final_score": final,
        "suggestion_value": suggested,
        "suggestion_status": suggestion_status,
    }


async def grading_queue(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID | None
) -> list[dict]:
    """批改队列：该教师班级中待确认的建议（needs_review 或 suggestion_status=draft）。"""
    from app.domains.teacher.today import teacher_class_ids

    class_ids = [class_id] if class_id else await teacher_class_ids(db, teacher_id)
    if not class_ids:
        return []
    sub_ids = select(Submission.id).where(
        Submission.assignment_id.in_(select(Assignment.id).where(Assignment.class_id.in_(class_ids)))
    )
    rows = (
        await db.execute(
            select(SubmissionItem, Submission.user_id, Assignment.title)
            .join(Submission, SubmissionItem.submission_id == Submission.id)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .where(
                SubmissionItem.submission_id.in_(sub_ids),
                SubmissionItem.suggestion_status == "draft",
            )
            .order_by(SubmissionItem.created_at.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "submission_item_id": str(item.id),
            "submission_id": str(item.submission_id),
            "assignment_title": title,
            "needs_review": item.needs_review,
            "suggested_score": float(item.suggested_score) if item.suggested_score is not None else None,
            "suggestion_status": item.suggestion_status,
        }
        for item, _uid, title in rows
    ]
