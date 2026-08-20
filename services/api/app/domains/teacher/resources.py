"""M3 教师端：资源 / 预处理 / 理解（§14）。

- 上传复用现有受控文件链（present 为目的占位：创建受控异步任务，不重复对象存储）；
- preprocess_course / understand_document 通过业务任务包装（queued→…）；
- 引用必须含资源 ID/页码或切片定位；检索继续复用 /tools/retrieve。
"""

from __future__ import annotations

import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.teacher.scope import assert_teacher_in_class
from app.models.teacher import TeacherTask

ERR_NOT_FOUND = 40400


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


def _serialize_task(t: TeacherTask) -> dict:
    return {
        "task_id": str(t.id),
        "capability": t.capability,
        "status": t.status,
        "progress": t.progress,
        "artifact_id": str(t.artifact_id) if t.artifact_id else None,
        "error_code": t.error_code,
        "created_at": t.created_at.isoformat() if t.created_at else None,
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
            "client_request_id": client_request_id,
        },
    )
    await db.flush()
    return _serialize_task(task)


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
    return _serialize_task(task)


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
    return _serialize_task(task)


async def list_resources(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID | None
) -> list[dict]:
    stmt = select(TeacherTask).where(TeacherTask.owner_id == teacher_id)
    if class_id:
        stmt = stmt.where(TeacherTask.class_id == class_id)
    rows = (await db.execute(stmt.order_by(TeacherTask.created_at.desc()).limit(100))).scalars().all()
    return [_serialize_task(t) for t in rows]
