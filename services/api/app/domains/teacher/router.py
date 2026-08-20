"""M3 教师端 HTTP 路由（§「router 只做 HTTP 解析、鉴权、响应」）。

- 统一信封 {code,message,data}；错误码按 API v2.1；
- P0 主链 + Artifact/任务 + P1 教案/作业/批改/资源 + Capability Gateway；
- 静态路由（/queue、/generate 等）声明在 {id} 参数路由之前，避免被吞。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher import artifacts as art
from app.domains.teacher import (
    assessment,
    classroom,
    grading,
    insights,
    lessons,
    resources,
    today,
)
from app.domains.teacher.capability_gateway import run_capability
from app.domains.teacher.registry import build_teacher_registry
from app.domains.teacher.schemas import (
    AdaptLessonRequest,
    ApplyInsightRequest,
    ArtifactActionRequest,
    ArtifactUpdateRequest,
    BatchConfirmRequest,
    CancelTaskRequest,
    CapabilityRequest,
    ClassroomModeRequest,
    ConfirmGradeRequest,
    CreateAssignmentRequest,
    CreateLessonRequest,
    CreateSlidesRequest,
    ExplainRequest,
    GenerateQuizRequest,
    PreprocessRequest,
    PublishAssignmentRequest,
    SuggestGradeRequest,
    UnderstandRequest,
)
from app.domains.teacher.scope import require_teacher_role
from app.gateway.auth import get_current_user
from app.models.database import get_db
from app.models.teacher import TeacherTask

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


def _ok(data) -> dict:
    return {"code": 0, "message": "ok", "data": data}


def _req_id(request: Request) -> str | None:
    return request.headers.get("X-Request-Id")


def _idem(request: Request) -> str | None:
    return request.headers.get("Idempotency-Key")


# ==================== P0 主链 ====================


@router.get("/today")
async def get_today(
    date: str | None = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    data = await today.build_today(db, teacher_id, date=date)
    return _ok(data)


@router.get("/classes/{class_id}/insights")
async def class_insights(
    class_id: uuid.UUID,
    actionable: bool = False,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    result = await insights.compute_class_insights(db, teacher_id, class_id, actionable=actionable)
    return _ok({"insights": result})


@router.get("/classes/{class_id}/video-insights")
async def video_insights(
    class_id: uuid.UUID,
    lesson_id: uuid.UUID | None = None,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    return _ok(await classroom.video_insights(db, teacher_id, class_id, lesson_id=lesson_id))


@router.post("/classes/{class_id}/classroom-mode")
async def classroom_mode(
    class_id: uuid.UUID,
    req: ClassroomModeRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    return _ok(
        await classroom.set_classroom_mode(
            db, teacher_id, class_id,
            enabled=req.enabled, lesson_id=req.lesson_id, duration_minutes=req.duration_minutes,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key or _idem(request),
            request_id=_req_id(request),
        )
    )


# ---------------- 教案 ----------------


@router.post("/lessons/adapt")
async def adapt_lesson(req: AdaptLessonRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await lessons.adapt_lesson(
            db, teacher_id, req.class_id,
            topic=req.topic, source_artifact_id=req.source_artifact_id,
            source_refs=req.source_refs, requirements=req.requirements,
            duration_minutes=req.duration_minutes, client_request_id=_req_id(request) or str(uuid.uuid4()),
        )
    )


@router.get("/lessons")
async def list_lessons(class_id: uuid.UUID | None = None, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok({"lessons": await lessons.list_lessons(db, teacher_id, class_id)})


@router.post("/lessons")
async def create_lesson(req: CreateLessonRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await lessons.create_lesson(
            db, teacher_id, req.class_id,
            title=req.title, topic=req.topic, duration_minutes=req.duration_minutes, content=req.content,
        )
    )


@router.get("/lessons/{lesson_id}")
async def get_lesson(lesson_id: uuid.UUID, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(await lessons.get_lesson(db, teacher_id, lesson_id))


@router.post("/lessons/{lesson_id}/apply-insight")
async def apply_insight(
    lesson_id: uuid.UUID, req: ApplyInsightRequest, insight_summary: str | None = None,
    user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    # 由 insight_id 解析 summary（调用方传入 insight_summary 时优先用其内容）
    summary = insight_summary or ""
    return _ok(
        await lessons.apply_insight_to_lesson(
            db, teacher_id, lesson_id, insight_summary=summary, version=req.version, instruction=req.instruction,
        )
    )


@router.post("/lessons/{lesson_id}/slides")
async def create_slides(lesson_id: uuid.UUID, req: CreateSlidesRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(await lessons.create_slides(db, teacher_id, lesson_id, version=req.version, style=req.style, requirements=req.requirements))


@router.post("/lessons/{lesson_id}/explainer")
async def create_explainer(lesson_id: uuid.UUID, req: ExplainRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    # 独立的讲解接口：由题目与参考解法生成 explanation artifact
    return _ok(
        await lessons.create_explainer(
            db, teacher_id, None,
            question=req.question, reference_solution=req.reference_solution, target_minutes=req.target_minutes,
        )
    )


# ---------------- 出题 / 作业 ----------------


@router.post("/quizzes/generate")
async def generate_quiz(req: GenerateQuizRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await assessment.generate_quiz(
            db, teacher_id, req.class_id,
            knowledge_points=req.knowledge_points, count=req.count,
            question_types=req.question_types.model_dump(), difficulty=req.difficulty.model_dump(),
            exclude_hashes=req.exclude_hashes, client_request_id=_req_id(request) or str(uuid.uuid4()),
        )
    )


@router.get("/assignments")
async def list_assignments(class_id: uuid.UUID | None = None, status: str | None = None, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok({"assignments": await assessment.list_assignments(db, teacher_id, class_id, status)})


@router.post("/assignments")
async def create_assignment(req: CreateAssignmentRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await assessment.create_assignment(
            db, teacher_id, req.class_id,
            title=req.title, artifact_id=req.artifact_id, client_assignment_id=req.client_assignment_id, deadline=req.deadline,
        )
    )


@router.post("/assignments/{assignment_id}/publish")
async def publish_assignment(assignment_id: uuid.UUID, req: PublishAssignmentRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    clazz = await _assignment_class(db, assignment_id)
    return _ok(
        await assessment.publish_assignment(
            db, teacher_id, clazz, assignment_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key, request_id=None,
        )
    )


@router.post("/assignments/{assignment_id}/close")
async def close_assignment(assignment_id: uuid.UUID, req: ArtifactActionRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    clazz = await _assignment_class(db, assignment_id)
    return _ok(
        await assessment.close_assignment(
            db, teacher_id, clazz, assignment_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key, request_id=None,
        )
    )


@router.post("/assignments/{assignment_id}/archive")
async def archive_assignment(assignment_id: uuid.UUID, req: ArtifactActionRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    clazz = await _assignment_class(db, assignment_id)
    return _ok(
        await assessment.archive_assignment(
            db, teacher_id, clazz, assignment_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key, request_id=None,
        )
    )


async def _assignment_class(db, assignment_id: uuid.UUID) -> uuid.UUID:
    from app.models.coursework import Assignment

    a = await db.get(Assignment, assignment_id)
    if a is None or a.deleted_at is not None:
        from app.domains.teacher.scope import raise_http

        raise_http(40400, 404, "not_found", recoverable=False)
    return a.class_id


# ---------------- 批改 ----------------


@router.get("/grading/queue")
async def grading_queue(class_id: uuid.UUID | None = None, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok({"queue": await grading.grading_queue(db, teacher_id, class_id)})


@router.post("/grading/{submission_item_id}/suggest")
async def suggest_grade(submission_item_id: uuid.UUID, req: SuggestGradeRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await grading.suggest_grade(
            db, teacher_id, req.class_id, submission_item_id,
            client_request_id=req.client_request_id,
        )
    )


@router.get("/grading/{submission_item_id}")
async def get_grading(submission_item_id: uuid.UUID, class_id: uuid.UUID | None = None, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    require_teacher_role(user)
    item = await db.get(__import__("app.models.coursework", fromlist=["SubmissionItem"]).SubmissionItem, submission_item_id)
    from app.domains.teacher.grading import _serialize_suggestion

    if item is None or item.deleted_at is not None:
        from app.domains.teacher.scope import raise_http

        raise_http(40400, 404, "not_found", recoverable=False)
    return _ok(_serialize_suggestion(item))


@router.post("/grading/{submission_item_id}/confirm")
async def confirm_grade(submission_item_id: uuid.UUID, req: ConfirmGradeRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)

    clazz = await _grade_class(db, submission_item_id)
    return _ok(
        await grading.confirm_grade(
            db, teacher_id, clazz, submission_item_id,
            suggestion_id=req.suggestion_id, decision=req.decision, final_score=req.final_score,
            teacher_feedback=req.teacher_feedback, version=req.version,
            client_request_id=str(uuid.uuid4()), idempotency_key=_idem(request),
            request_id=_req_id(request),
        )
    )


@router.post("/grading/batch-confirm")
async def batch_confirm(req: BatchConfirmRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    results = []
    for it in req.items:
        try:
            clazz = await _grade_class(db, it.submission_item_id)
            r = await grading.confirm_grade(
                db, teacher_id, clazz, it.submission_item_id,
                suggestion_id=it.suggestion_id, decision=it.decision, final_score=it.final_score,
                teacher_feedback=it.teacher_feedback, version=it.version,
                client_request_id=str(uuid.uuid4()), idempotency_key=None,
            )
            results.append({"ok": True, "submission_item_id": str(it.submission_item_id), "result": r})
        except Exception as exc:  # noqa: BLE001

            results.append({"ok": False, "submission_item_id": str(it.submission_item_id), "error": str(exc)})
    return _ok({"results": results})


async def _grade_class(db, submission_item_id: uuid.UUID) -> uuid.UUID:
    from app.models.coursework import Assignment, Submission, SubmissionItem

    item = await db.get(SubmissionItem, submission_item_id)
    if item is None:
        from app.domains.teacher.scope import raise_http

        raise_http(40400, 404, "not_found", recoverable=False)
    sub = await db.get(Submission, item.submission_id)
    a = await db.get(Assignment, sub.assignment_id) if sub else None
    return a.class_id if a else None


# ---------------- 资源 ----------------


@router.get("/resources")
async def list_resources(class_id: uuid.UUID | None = None, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok({"resources": await resources.list_resources(db, teacher_id, class_id)})


@router.post("/resources/upload")
async def upload_resource(file: UploadFile = File(...), user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await resources.resource_upload(db, teacher_id, None, file, client_request_id=str(uuid.uuid4()))
    )


@router.post("/resources/{resource_id}/preprocess")
async def preprocess(resource_id: str, req: PreprocessRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await resources.resource_preprocess(
            db, teacher_id, None, resource_id, client_request_id=req.client_request_id
        )
    )


@router.post("/resources/{resource_id}/understand")
async def understand(resource_id: str, req: UnderstandRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await resources.resource_understand(
            db, teacher_id, None, resource_id,
            question=req.question, output_type=req.output_type, client_request_id=req.client_request_id,
        )
    )


# ---------------- Artifact 与任务 ----------------


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: uuid.UUID, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    a = await art.get_owned_artifact(db, teacher_id, artifact_id)
    return _ok(art._serialize_artifact(a))


@router.put("/artifacts/{artifact_id}")
async def update_artifact(artifact_id: uuid.UUID, req: ArtifactUpdateRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    a, created = await art.update_artifact(db, teacher_id, artifact_id, version=req.version, payload=req.content, source_refs=req.source_refs)
    await db.flush()
    return _ok({"artifact": art._serialize_artifact(a), "created_new_version": created})


@router.post("/artifacts/{artifact_id}/confirm")
async def confirm_artifact(artifact_id: uuid.UUID, req: ArtifactActionRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await art.confirm_artifact(
            db, teacher_id, artifact_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key or _idem(request),
            request_id=_req_id(request),
        )
    )


@router.post("/artifacts/{artifact_id}/publish")
async def publish_artifact(artifact_id: uuid.UUID, req: ArtifactActionRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await art.publish_artifact(
            db, teacher_id, artifact_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key or _idem(request),
            request_id=_req_id(request),
        )
    )


@router.post("/artifacts/{artifact_id}/archive")
async def archive_artifact(artifact_id: uuid.UUID, req: ArtifactActionRequest, request: Request, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    return _ok(
        await art.archive_artifact(
            db, teacher_id, artifact_id,
            client_request_id=req.client_request_id, idempotency_key=req.idempotency_key or _idem(request),
            request_id=_req_id(request),
        )
    )


@router.get("/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    t = await db.get(TeacherTask, task_id)
    if t is None or t.owner_id != teacher_id:
        from app.domains.teacher.scope import raise_http

        raise_http(40400, 404, "not_found", recoverable=False)
    return _ok(
        {
            "task_id": str(t.id),
            "capability": t.capability,
            "status": t.status,
            "progress": t.progress,
            "artifact_id": str(t.artifact_id) if t.artifact_id else None,
            "error_code": t.error_code,
        }
    )


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: uuid.UUID, req: CancelTaskRequest, user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    teacher_id = require_teacher_role(user)
    t = await db.get(TeacherTask, task_id)
    if t is None or t.owner_id != teacher_id:
        from app.domains.teacher.scope import raise_http

        raise_http(40400, 404, "not_found", recoverable=False)
    if t.status in ("queued", "running"):
        t.status = "cancelled"
        await db.flush()
    return _ok({"task_id": str(t.id), "status": t.status})


# ==================== Capability Gateway（内部受控） ====================


@router.get("/capabilities")
async def list_capabilities(user: dict = Depends(get_current_user)):
    require_teacher_role(user)
    from app.domains.teacher.capability_gateway import VALID_CAPABILITIES

    return _ok({"capabilities": sorted(VALID_CAPABILITIES)})


@router.post("/capabilities/{capability}")
async def run_capability_endpoint(
    capability: str,
    req: CapabilityRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    teacher_id = require_teacher_role(user)
    result = await run_capability(
        db, teacher_id,
        scene=req.scene, class_id=req.class_id, capability=capability,
        payload=req.payload, source_refs=req.source_refs,
        client_request_id=req.client_request_id,
    )
    # 星辰/本地执行后生成 draft artifact
    artifact = await art.create_artifact(
        db,
        owner_id=teacher_id,
        artifact_type=_capability_artifact_type(capability),
        scene=req.scene,
        class_id=req.class_id,
        payload=result["payload"],
        source_refs=req.source_refs,
        engine=result["engine"],
        degraded=result["degraded"],
        warnings=result.get("warnings") or [],
        validation=result.get("validation", {}),
    )
    db.add(artifact)
    await db.flush()
    return _ok(
        {
            "artifact_id": str(artifact.id),
            "status": artifact.status,
            "engine": artifact.engine,
            "degraded": artifact.degraded,
            "warnings": artifact.warnings,
        }
    )


def _capability_artifact_type(capability: str) -> str:
    return {
        "adapt_lesson": "lesson_plan",
        "create_slides": "slide_deck",
        "create_quiz": "quiz_set",
        "suggest_grade": "grading_suggestion",
        "explain_problem": "explanation",
        "preprocess_course": "preprocess",
        "understand_document": "document",
    }.get(capability, "artifact")


# ==================== teacher registry 暴露（供但ler 集成测试/影子运行） ====================


def get_teacher_registry():

    return build_teacher_registry()
