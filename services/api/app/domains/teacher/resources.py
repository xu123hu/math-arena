"""M3 教师端：资源 / 预处理 / 理解（§14）。

- 上传复用现有受控文件链（创建受控异步任务，不重复对象存储）；
- preprocess_course / understand_document 通过业务任务包装（queued→…）；
- 引用必须含资源 ID/页码或切片定位；检索继续复用 /tools/retrieve；
- 响应对齐前端 TeacherResource / UploadTicket 契约（审计 C-04）。
"""

from __future__ import annotations

import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.scope import assert_teacher_in_class
from app.models.teacher import TeacherTask

ERR_NOT_FOUND = 40400

# 任务状态 → 前端资源状态
_STATUS_MAP = {
    "queued": "preprocessing",
    "running": "preprocessing",
    "succeeded": "ready",
    "failed": "failed",
    "cancelled": "cancelled",
}


async def _create_task(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    capability: str,
    payload: dict,
    client_request_id: str | None = None,
) -> TeacherTask:
    t = TeacherTask(
        owner_id=teacher_id,
        class_id=class_id,
        capability=capability,
        status="queued",
        payload={**payload, "client_request_id": client_request_id}
        if client_request_id
        else payload,
    )
    db.add(t)
    await db.flush()
    return t


def _serialize_resource(t: TeacherTask) -> dict:
    """对齐前端 TeacherResource 契约（task 以 resource 维度呈现）。"""
    payload = t.payload or {}
    name = payload.get("filename") or payload.get("resource_id") or "教学材料"
    return {
        "resource_id": str(t.id),
        "name": str(name),
        "file_type": payload.get("file_type") or "file",
        "size_bytes": int(payload.get("size_bytes") or 0),
        "status": _STATUS_MAP.get(t.status, "preprocessing"),
        "task_id": str(t.id),
        "error": t.error_code,
        "pages": (t.result or {}).get("pages") or [],
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _serialize_ticket(t: TeacherTask) -> dict:
    """对齐前端 UploadTicket 契约。"""
    return {
        "resource_id": str(t.id),
        "task_id": str(t.id),
        "status": "uploading",
    }


async def resource_upload(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    file: UploadFile,
    client_request_id: str,
) -> dict:
    if class_id:
        await assert_teacher_in_class(db, teacher_id, class_id)
    # 受控上传任务：文件对象随后由工作进程经受控对象存储写入真实资源落库
    task = await _create_task(
        db,
        teacher_id,
        class_id,
        capability="resource.upload",
        payload={
            "filename": file.filename,
            "file_type": file.content_type or "file",
            "size_bytes": 0,
            "client_request_id": client_request_id,
        },
    )
    await db.flush()
    return _serialize_ticket(task)


async def resource_preprocess(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    resource_id: str,
    client_request_id: str,
) -> dict:
    if class_id:
        await assert_teacher_in_class(db, teacher_id, class_id)
    task = await _create_task(
        db,
        teacher_id,
        class_id,
        capability="preprocess_course",
        payload={"resource_id": resource_id, "client_request_id": client_request_id},
    )
    await db.flush()
    return _serialize_resource(task)


async def resource_understand(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    class_id: uuid.UUID | None,
    resource_id: str,
    *,
    question: str | None,
    output_type: str | None,
    client_request_id: str,
) -> dict:
    if class_id:
        await assert_teacher_in_class(db, teacher_id, class_id)
    task = await _create_task(
        db,
        teacher_id,
        class_id,
        capability="understand_document",
        payload={
            "resource_id": resource_id,
            "question": question,
            "output_type": output_type,
            "client_request_id": client_request_id,
        },
    )
    await db.flush()
    return _serialize_resource(task)


async def list_resources(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID | None
) -> list[dict]:
    stmt = select(TeacherTask).where(TeacherTask.owner_id == teacher_id)
    if class_id:
        stmt = stmt.where(TeacherTask.class_id == class_id)
    rows = (await db.execute(stmt.order_by(TeacherTask.created_at.desc()).limit(100))).scalars().all()
    return [_serialize_resource(t) for t in rows]
