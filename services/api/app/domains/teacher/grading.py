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
from app.models.file import File
from app.models.teacher import TeacherAction, TeachingArtifact

ERR_CONFIRMATION_REQUIRED = 42210
ERR_NOT_FOUND = 40400
ERR_VALIDATION = 40001
ERR_DUPLICATE = 40902


def _now() -> datetime:
    return datetime.now(UTC)


def _student_label(item_no: int) -> str:
    """匿名学生标签（批改页默认匿名，不解锁个体身份）。"""
    return f"作答 #{item_no:03d}"


def _queue_status(item: SubmissionItem) -> str:
    """队列状态：unprocessed | low_confidence | confirmed（对齐前端 GradingQueueItem）。"""
    if item.suggestion_status in ("accepted", "overridden", "applied"):
        return "confirmed"
    if item.needs_review or item.verdict == "pending_review":
        return "low_confidence"
    return "unprocessed"


def _serialize_queue_item(item: SubmissionItem) -> dict:
    return {
        "submission_item_id": str(item.id),
        "student_label": _student_label(item.item_no),
        "status": _queue_status(item),
        "confidence": float(item.suggestion_confidence or 0.0),
        "suggestion_score": (
            float(item.suggested_score) if item.suggested_score is not None else None
        ),
        "teacher_final_score": (
            float(item.teacher_final_score) if item.teacher_final_score is not None else None
        ),
    }


def _serialize_suggestion(
    item: SubmissionItem, *, suggestion_id: str | None = None, version: int = 1
) -> dict:
    """对齐前端 GradingSuggestion 契约。"""
    rationale = item.suggestion_rationale or {}
    evidence = "；".join(
        f"{k}={v}" for k, v in rationale.items() if isinstance(v, (str, int, float, bool))
    )
    return {
        "suggestion_id": suggestion_id or "",
        "submission_item_id": str(item.id),
        "student_label": _student_label(item.item_no),
        "original_answer": item.answer_text or "",
        "file_id": str(item.file_id) if item.file_id else None,
        "scoring_standard": "按题目评分点逐项给分（客观题规则判定，主观题人工复核）",
        "suggestion_score": (
            float(item.suggested_score) if item.suggested_score is not None else None
        ),
        "confidence": float(item.suggestion_confidence or 0.0),
        "evidence": evidence or "本地规则/模型建议，待教师确认",
        "review_needed": bool(item.needs_review),
        "teacher_final_score": (
            float(item.teacher_final_score) if item.teacher_final_score is not None else None
        ),
        "teacher_feedback": item.teacher_feedback,
        "decision": item.suggestion_status,  # draft|accepted|overridden|applied
        "version": version,
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


async def _load_persisted_quiz_item(
    db: AsyncSession, sub: Submission, item: SubmissionItem
) -> QuizItem | None:
    """Return the submitted item's persisted quiz context, if it still exists."""
    if sub.quiz_id is None:
        return None
    return (
        await db.execute(
            select(QuizItem).where(
                QuizItem.quiz_id == sub.quiz_id,
                QuizItem.item_no == item.item_no,
                QuizItem.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


def _normalize_objective_answer(value: str | None) -> str:
    return (value or "").strip().casefold()


def _objective_score(
    item: SubmissionItem, quiz_item: QuizItem | None
) -> tuple[float, float, bool, str]:
    """Score objective answers only when a persisted standard answer is available."""
    if quiz_item is None:
        return 0.0, 0.0, True, "缺少已持久化题目上下文，无法依据标准答案判定"
    standard_answer = _normalize_objective_answer(quiz_item.answer)
    if not standard_answer:
        return 0.0, 0.0, True, "缺少标准答案证据，无法依据标准答案判定"
    is_correct = _normalize_objective_answer(item.answer_text) == standard_answer
    return (
        1.0 if is_correct else 0.0,
        1.0,
        False,
        "已依据已持久化标准答案判定：答案一致"
        if is_correct
        else "已依据已持久化标准答案判定：答案不一致",
    )


async def suggest_grade(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    submission_item_id: uuid.UUID,
    *,
    client_request_id: str,
) -> dict:
    item, sub = await _load_item_in_class(db, teacher_id, submission_item_id)

    # 客观题规则；否则本地建议 + 人工复核（星辰不可用时降级）
    if item.q_type in ("choice", "judge"):
        quiz_item = await _load_persisted_quiz_item(db, sub, item)
        suggested, conf, needs_review, detail = _objective_score(item, quiz_item)
        rationale = {"type": "rule", "detail": detail}
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
    # 对齐前端 GradingSuggestion：建议对象直接位于 data 顶层
    return _serialize_suggestion(
        item, suggestion_id=str(artifact.id), version=artifact.version
    )


async def grading_detail(
    db: AsyncSession, teacher_id: uuid.UUID, submission_item_id: uuid.UUID
) -> dict:
    """批改详情（对齐前端 GradingDetail）：尚未建议时先自动生成本地建议。"""
    item, _sub = await _load_item_in_class(db, teacher_id, submission_item_id)
    quiz_item = await _load_persisted_quiz_item(db, _sub, item)
    assignment = await db.get(Assignment, _sub.assignment_id) if _sub.assignment_id else None
    suggestion: dict | None = None
    if item.suggested_score is None:
        # 尚无建议：自动生成本地建议（范围校验由 suggest_grade 内部再次执行）
        suggestion = await suggest_grade(
            db, teacher_id, assignment.class_id if assignment else None, submission_item_id,
            client_request_id=f"auto:{submission_item_id}",
        )
    else:
        artifact = (
            await db.execute(
                select(TeachingArtifact)
                .where(
                    TeachingArtifact.owner_id == teacher_id,
                    TeachingArtifact.artifact_type == "grading_suggestion",
                    TeachingArtifact.deleted_at.is_(None),
                    TeachingArtifact.payload["submission_item_id"].as_string()
                    == str(submission_item_id),
                )
                .order_by(TeachingArtifact.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if artifact is not None:
            suggestion = _serialize_suggestion(
                item, suggestion_id=str(artifact.id), version=artifact.version
            )
        elif item.suggestion_status not in ("accepted", "overridden", "applied"):
            suggestion = await suggest_grade(
                db,
                teacher_id,
                assignment.class_id if assignment else None,
                submission_item_id,
                client_request_id=f"repair:{submission_item_id}",
            )
    return {
        **_serialize_queue_item(item),
        "original_answer": item.answer_text or "",
        "file_id": str(item.file_id) if item.file_id else None,
        "scoring_standard": "按题目评分点逐项给分（客观题规则判定，主观题人工复核）",
        "assignment_title": assignment.title if assignment and assignment.deleted_at is None else None,
        "question_text": quiz_item.question_text if quiz_item else None,
        "question_type": quiz_item.q_type if quiz_item else None,
        "options": quiz_item.options if quiz_item else None,
        "standard_answer": quiz_item.answer if quiz_item and quiz_item.answer else None,
        "answer_analysis": quiz_item.answer_analysis if quiz_item else None,
        "suggestion": suggestion or _serialize_suggestion(item),
    }


async def grading_file(
    db: AsyncSession, teacher_id: uuid.UUID, submission_item_id: uuid.UUID
) -> tuple[bytes, str, str]:
    """读取教师班级范围内的学生原始照片，不生成公开 URL。"""
    item, _sub = await _load_item_in_class(db, teacher_id, submission_item_id)
    if item.file_id is None:
        raise_http(ERR_NOT_FOUND, 404, "file_not_found", recoverable=False)
    file_obj = await db.get(File, item.file_id)
    if file_obj is None or file_obj.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "file_not_found", recoverable=False)
    try:
        from app.domains.files.router import _read_file_bytes

        content = _read_file_bytes(file_obj)
    except Exception:
        raise_http(ERR_NOT_FOUND, 404, "file_content_not_found", recoverable=False)
    return content, file_obj.mime or "application/octet-stream", file_obj.filename


async def _mastery_update_from_confirmed(
    db: AsyncSession, item: SubmissionItem, sub: Submission
) -> None:
    """学情只消费已确认终值：按该题知识点更新掌握度（best-effort，失败不阻断正式写）。"""
    try:
        if item.teacher_final_score is None:
            return
        if sub.quiz_id is None:
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

    # 幂等：同键已处理 → 返回首次结果（含建议快照）
    if idempotency_key:
        existing = (
            await db.execute(
                select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            snap = _serialize_suggestion(item, suggestion_id=str(suggestion_id))
            return {**snap, "replayed": True}

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
    await db.flush()

    # 汇总 Submission.total_score 重算（best-effort）
    total = await db.scalar(
        select(func.sum(SubmissionItem.score)).where(SubmissionItem.submission_id == sub.id)
    )
    if total is not None:
        sub.total_score = total
    remaining = await db.scalar(
        select(func.count(SubmissionItem.id)).where(
            SubmissionItem.submission_id == sub.id,
            SubmissionItem.deleted_at.is_(None),
            SubmissionItem.confirmed_at.is_(None),
        )
    )
    sub.status = "graded" if int(remaining or 0) == 0 else "pending_review"

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
    # 对齐前端 GradingSuggestion：确认后返回最新建议快照（decision=accepted/overridden）
    return _serialize_suggestion(
        item, suggestion_id=str(suggestion_id), version=artifact.version
    )


async def grading_queue(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID | None
) -> list[dict]:
    """批改队列（对齐前端 GradingQueueItem[]）。

    覆盖三类：unprocessed（未建议）、low_confidence（待复核）、confirmed（已确认）。
    """
    from app.domains.teacher.today import teacher_class_ids

    if class_id is not None:
        from app.domains.teacher.scope import assert_teacher_in_class

        await assert_teacher_in_class(db, teacher_id, class_id)
        class_ids = [class_id]
    else:
        class_ids = await teacher_class_ids(db, teacher_id)
    if not class_ids:
        return []
    rows = (
        await db.execute(
            select(SubmissionItem)
            .join(Submission, SubmissionItem.submission_id == Submission.id)
            .join(Assignment, Submission.assignment_id == Assignment.id)
            .where(
                Assignment.class_id.in_(class_ids),
                Assignment.deleted_at.is_(None),
                Submission.deleted_at.is_(None),
                SubmissionItem.deleted_at.is_(None),
            )
            .order_by(SubmissionItem.created_at.desc())
            .limit(100)
        )
    ).scalars().all()
    return [_serialize_queue_item(item) for item in rows]
