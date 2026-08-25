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

import hashlib
import json
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
        "attachments": item.attachments or [],
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


def _quiz_evidence(quiz_item: QuizItem | None) -> dict | None:
    """Immutable persisted facts that make an objective suggestion auditable."""
    if quiz_item is None:
        return None
    return {
        "quiz_item_id": str(quiz_item.id),
        "q_type": quiz_item.q_type,
        "standard_answer": quiz_item.answer,
        "question_text_digest": hashlib.sha256(
            quiz_item.question_text.encode("utf-8")
        ).hexdigest(),
        "kp_code": quiz_item.kp_code,
    }


def _suggestion_fingerprint(
    item: SubmissionItem, quiz_evidence: dict | None
) -> str:
    """Bind an artifact to the exact suggestion snapshot it was created from."""
    snapshot = {
        "submission_item_id": str(item.id),
        "q_type": item.q_type,
        "answer_text": item.answer_text,
        "file_id": str(item.file_id) if item.file_id else None,
        "suggested_score": str(item.suggested_score) if item.suggested_score is not None else None,
        "suggestion_rationale": item.suggestion_rationale or {},
        "suggestion_feedback": item.suggestion_feedback,
        "suggestion_confidence": (
            str(item.suggestion_confidence)
            if item.suggestion_confidence is not None
            else None
        ),
        "needs_review": bool(item.needs_review),
        "quiz_evidence": quiz_evidence,
    }
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _confirmation_binding(
    *,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    submission_item_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    decision: str,
    final_score: float | None,
    teacher_feedback: str | None,
    version: int,
) -> dict:
    request = {
        "decision": decision,
        "final_score": str(final_score),
        "teacher_feedback": teacher_feedback,
        "version": version,
    }
    request_json = json.dumps(request, ensure_ascii=False, sort_keys=True)
    return {
        "teacher_id": str(teacher_id),
        "action": "grade.confirm",
        "class_id": str(class_id),
        "submission_item_id": str(submission_item_id),
        "suggestion_id": str(suggestion_id),
        "decision": decision,
        "request_fingerprint": hashlib.sha256(request_json.encode("utf-8")).hexdigest(),
    }


def _action_matches_binding(action: TeacherAction, binding: dict) -> bool:
    return (action.details or {}).get("binding") == binding


async def _lock_idempotency_key(db: AsyncSession, idempotency_key: str) -> None:
    """Serialize same-key confirms even before their audit row exists."""
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtext(idempotency_key)))
    )


async def lock_batch_submission_items(
    db: AsyncSession, submission_item_ids: list[uuid.UUID]
) -> None:
    """Acquire every batch resource lock in a global order before grading any item."""
    for submission_item_id in sorted(set(submission_item_ids), key=str):
        await db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(f"grading-batch-item:{submission_item_id}")
                )
            )
        )


def _add_confirmation_action(
    db: AsyncSession,
    *,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    client_request_id: str,
    idempotency_key: str | None,
    request_id: str | None,
    binding: dict,
    final_score: float,
    replayed: bool,
) -> None:
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
                "binding": binding,
                "decision": binding["decision"],
                "final_score": final_score,
                "replayed": replayed,
            },
        )
    )


async def _load_item_in_class(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    submission_item_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> tuple[SubmissionItem, Submission, Assignment]:
    from app.domains.teacher.scope import assert_teacher_in_class

    if for_update:
        item = await db.scalar(
            select(SubmissionItem)
            .where(SubmissionItem.id == submission_item_id)
            .with_for_update()
        )
    else:
        item = await db.get(SubmissionItem, submission_item_id)
    if item is None or item.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)
    sub = await db.get(Submission, item.submission_id)
    if sub is None or sub.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)
    a = (
        await db.get(Assignment, sub.assignment_id)
        if sub.assignment_id is not None
        else None
    )
    if a is None or a.deleted_at is not None:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)
    await assert_teacher_in_class(db, teacher_id, a.class_id)
    return item, sub, a


async def _load_persisted_quiz_item(
    db: AsyncSession, sub: Submission, item: SubmissionItem
) -> tuple[QuizItem | None, str | None]:
    """Return one trusted persisted context, or a reason why none is trustworthy."""
    if sub.quiz_id is None:
        return None, "missing"
    rows = (
        await db.execute(
            select(QuizItem).where(
                QuizItem.quiz_id == sub.quiz_id,
                QuizItem.item_no == item.item_no,
                QuizItem.deleted_at.is_(None),
            ).limit(2)
        )
    ).scalars().all()
    if len(rows) != 1:
        return None, "missing" if not rows else "ambiguous"
    quiz_item = rows[0]
    if quiz_item.q_type != item.q_type:
        return None, "q_type_mismatch"
    return quiz_item, None


def _normalize_objective_answer(value: str | None) -> str:
    return (value or "").strip().casefold()


def _objective_score(
    item: SubmissionItem, quiz_item: QuizItem | None, context_reason: str | None
) -> tuple[float, float, bool, str]:
    """Score objective answers only when a persisted standard answer is available."""
    if context_reason == "ambiguous":
        return 0.0, 0.0, True, "存在重复的已持久化题目上下文，无法依据标准答案判定"
    if context_reason == "q_type_mismatch":
        return 0.0, 0.0, True, "作答题型与已持久化题目题型不一致，无法依据标准答案判定"
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


def _untrusted_context_suggestion(
    item: SubmissionItem,
    context_reason: str | None,
    *,
    suggestion_id: str | None = None,
    version: int = 1,
) -> dict:
    """Do not present a stale suggestion as trustworthy after its context changes."""
    _, confidence, _, evidence = _objective_score(item, None, context_reason)
    suggestion = _serialize_suggestion(
        item, suggestion_id=suggestion_id, version=version
    )
    suggestion.update(
        suggestion_score=None,
        confidence=confidence,
        evidence=evidence,
        review_needed=True,
    )
    return suggestion


async def suggest_grade(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    submission_item_id: uuid.UUID,
    *,
    client_request_id: str,
) -> dict:
    item, sub, assignment = await _load_item_in_class(db, teacher_id, submission_item_id)
    if class_id is not None and class_id != assignment.class_id:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)

    # 客观题规则；否则本地建议 + 人工复核（星辰不可用时降级）
    if item.q_type in ("choice", "judge"):
        quiz_item, context_reason = await _load_persisted_quiz_item(db, sub, item)
        suggested, conf, needs_review, detail = _objective_score(
            item, quiz_item, context_reason
        )
        quiz_evidence = _quiz_evidence(quiz_item)
        rationale = {"type": "rule", "detail": detail}
        feedback = None
    else:
        suggested, conf = 0.0, 0.3
        quiz_evidence = None
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
        class_id=assignment.class_id,
        payload={
            **_serialize_suggestion(item),
            "quiz_evidence": quiz_evidence,
            "suggestion_fingerprint": _suggestion_fingerprint(item, quiz_evidence),
        },
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
    item, _sub, assignment = await _load_item_in_class(db, teacher_id, submission_item_id)
    quiz_item, _context_reason = await _load_persisted_quiz_item(db, _sub, item)
    has_untrusted_objective_context = (
        item.q_type in ("choice", "judge") and _context_reason is not None
    )
    suggestion: dict | None = None
    if item.suggested_score is None:
        # 尚无建议：自动生成本地建议（范围校验由 suggest_grade 内部再次执行）
        suggestion = await suggest_grade(
            db, teacher_id, assignment.class_id if assignment else None, submission_item_id,
            client_request_id=f"auto:{submission_item_id}",
        )
    elif has_untrusted_objective_context:
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
        suggestion = _untrusted_context_suggestion(
            item,
            _context_reason,
            suggestion_id=str(artifact.id) if artifact is not None else None,
            version=artifact.version if artifact is not None else 1,
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
    queue_item = _serialize_queue_item(item)
    if has_untrusted_objective_context:
        queue_item.update(status="low_confidence", confidence=0.0, suggestion_score=None)
    return {
        **queue_item,
        "original_answer": item.answer_text or "",
        "file_id": str(item.file_id) if item.file_id else None,
        "attachments": item.attachments or [],
        "scoring_standard": "按题目评分点逐项给分（客观题规则判定，主观题人工复核）",
        "assignment_title": assignment.title if assignment and assignment.deleted_at is None else None,
        "question_text": quiz_item.question_text if quiz_item else None,
        "question_type": quiz_item.q_type if quiz_item else None,
        "options": quiz_item.options if quiz_item else None,
        "standard_answer": quiz_item.answer if quiz_item and quiz_item.answer else None,
        "answer_analysis": quiz_item.answer_analysis if quiz_item else None,
        "suggestion": suggestion
        or (
            _untrusted_context_suggestion(item, _context_reason)
            if has_untrusted_objective_context
            else _serialize_suggestion(item)
        ),
    }


async def grading_file(
    db: AsyncSession, teacher_id: uuid.UUID, submission_item_id: uuid.UUID
) -> tuple[bytes, str, str]:
    """读取教师班级范围内的学生原始照片，不生成公开 URL。"""
    item, _sub, _assignment = await _load_item_in_class(db, teacher_id, submission_item_id)
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
        quiz_item, context_reason = await _load_persisted_quiz_item(db, sub, item)
        if quiz_item is None or context_reason is not None:
            return
        kp_code = quiz_item.kp_code
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
    item, sub, assignment = await _load_item_in_class(
        db, teacher_id, submission_item_id, for_update=True
    )
    if class_id != assignment.class_id:
        raise_http(ERR_NOT_FOUND, 404, "not_found", recoverable=False)

    if decision not in ("accept", "override"):
        raise_http(ERR_VALIDATION, 422, "invalid_decision", recoverable=False)
    if decision == "override" and final_score is None:
        raise_http(ERR_VALIDATION, 422, "final_score_required", recoverable=True)
    requested_final = float(final_score) if final_score is not None else None

    binding = _confirmation_binding(
        teacher_id=teacher_id,
        class_id=class_id,
        submission_item_id=submission_item_id,
        suggestion_id=suggestion_id,
        decision=decision,
        final_score=requested_final,
        teacher_feedback=teacher_feedback,
        version=version,
    )
    if idempotency_key:
        await _lock_idempotency_key(db, idempotency_key)
        existing = await db.scalar(
            select(TeacherAction).where(TeacherAction.idempotency_key == idempotency_key)
        )
        if existing is not None:
            if not _action_matches_binding(existing, binding):
                raise_http(ERR_DUPLICATE, 409, "idempotency_conflict", recoverable=False)
            return {
                **_serialize_suggestion(
                    item, suggestion_id=str(suggestion_id), version=version
                ),
                "replayed": True,
            }

    if item.confirmed_at is not None:
        actions = (
            await db.execute(
                select(TeacherAction).where(
                    TeacherAction.teacher_id == teacher_id,
                    TeacherAction.action_type == "grade.confirm",
                )
            )
        ).scalars()
        if any(_action_matches_binding(action, binding) for action in actions):
            _add_confirmation_action(
                db,
                teacher_id=teacher_id,
                class_id=class_id,
                suggestion_id=suggestion_id,
                client_request_id=client_request_id,
                idempotency_key=idempotency_key,
                request_id=request_id,
                binding=binding,
                final_score=float(item.teacher_final_score or 0),
                replayed=True,
            )
            await db.flush()
            return {
                **_serialize_suggestion(
                    item, suggestion_id=str(suggestion_id), version=version
                ),
                "replayed": True,
            }
        raise_http(ERR_DUPLICATE, 409, "confirmation_conflict", recoverable=False)

    artifact = await get_owned_artifact(db, teacher_id, suggestion_id)
    artifact_payload = artifact.payload or {}
    if (
        artifact.artifact_type != "grading_suggestion"
        or artifact.class_id != assignment.class_id
        or artifact_payload.get("submission_item_id") != str(item.id)
    ):
        raise_http(ERR_VALIDATION, 422, "invalid_suggestion", recoverable=False)
    if artifact.version != version:
        raise_http(40901, 409, "version_conflict", recoverable=True)

    if decision == "override":
        final = requested_final
        suggestion_status = "overridden"
    else:
        quiz_item, context_reason = await _load_persisted_quiz_item(db, sub, item)
        if quiz_item is None or context_reason is not None:
            raise_http(
                ERR_CONFIRMATION_REQUIRED,
                422,
                "trusted_context_required",
                recoverable=True,
            )
        current_evidence = _quiz_evidence(quiz_item)
        recomputed, _confidence, needs_review, _detail = _objective_score(
            item, quiz_item, context_reason
        )
        artifact_score = artifact_payload.get("suggestion_score")
        evidence_matches = artifact_payload.get("quiz_evidence") == current_evidence
        fingerprint_matches = artifact_payload.get("suggestion_fingerprint") == _suggestion_fingerprint(
            item, current_evidence
        )
        if (
            item.q_type not in ("choice", "judge")
            or needs_review
            or item.needs_review
            or artifact_payload.get("review_needed") is not False
            or item.suggested_score is None
            or artifact_score is None
            or float(item.suggested_score) != recomputed
            or float(artifact_score) != recomputed
            or not evidence_matches
            or not fingerprint_matches
        ):
            raise_http(
                ERR_CONFIRMATION_REQUIRED,
                422,
                "suggestion_evidence_changed",
                recoverable=True,
            )
        final = recomputed
        suggestion_status = "accepted"

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

    _add_confirmation_action(
        db,
        teacher_id=teacher_id,
        class_id=class_id,
        suggestion_id=suggestion_id,
        client_request_id=client_request_id,
        idempotency_key=idempotency_key,
        request_id=request_id,
        binding=binding,
        final_score=final,
        replayed=False,
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
