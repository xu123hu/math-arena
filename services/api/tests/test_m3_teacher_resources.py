"""M3 教师端：资源/预处理/理解 → 异步任务（§14 / §7.5）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import async_session_factory
from app.models.teacher import TeacherTask
from app.models.question_bank import QuestionBank
from sqlalchemy import select
from tests._m3_helpers import make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_resource_upload_preprocess_understand_publish_and_download(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    content = "函数描述两个变量之间的对应关系。导数表示函数的瞬时变化率。".encode()
    r = await client.post("/api/teacher/resources/upload",
                          files={"file": ("lesson.txt", content, "text/plain")},
                          headers=_auth(tok))
    assert r.json()["code"] == 0
    resource_id = r.json()["data"]["resource_id"]
    assert r.json()["data"]["status"] == "ready"
    p = await client.post(f"/api/teacher/resources/{resource_id}/preprocess",
                          json={"client_request_id": "pp"}, headers=_auth(tok))
    assert p.json()["data"]["status"] == "ready"
    assert p.json()["data"]["slices"][0]["text"].startswith("函数描述")

    understood = await client.post(
        f"/api/teacher/resources/{resource_id}/understand",
        json={"question": "本文要点", "client_request_id": "ud"},
        headers=_auth(tok),
    )
    assert "导数" in understood.json()["data"]["summary"]

    published = await client.post(
        f"/api/teacher/resources/{resource_id}/publish", headers=_auth(tok)
    )
    assert published.json()["data"]["published"] is True
    listed = await client.get("/api/teacher/resources", headers=_auth(tok))
    row = next(x for x in listed.json()["data"]["resources"] if x["resource_id"] == resource_id)
    assert row["size_bytes"] == len(content)
    assert row["published"] is True
    downloaded = await client.get(
        f"/api/teacher/resources/{resource_id}/download", headers=_auth(tok)
    )
    assert downloaded.content == content


@pytest.mark.asyncio
async def test_resource_rejects_missing_and_cross_teacher(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        other = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    missing = await client.post(
        "/api/teacher/resources/not-a-resource/understand",
        json={"question": "本文要点", "client_request_id": "ud"},
        headers=_auth(tok),
    )
    assert missing.json()["code"] == 40400
    uploaded = await client.post(
        "/api/teacher/resources/upload",
        files={"file": ("private.txt", b"private", "text/plain")},
        headers=_auth(tok),
    )
    resource_id = uploaded.json()["data"]["resource_id"]
    denied = await client.get(
        f"/api/teacher/resources/{resource_id}/download",
        headers=_auth(token(other, "teacher")),
    )
    assert denied.json()["code"] == 40400


@pytest.mark.asyncio
async def test_uploaded_question_candidates_require_teacher_approval_before_bank_insert(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    uploaded = await client.post("/api/teacher/resources/upload", files={"file": ("math.txt", b"source", "text/plain")}, headers=_auth(tok))
    resource_id = uploaded.json()["data"]["resource_id"]
    candidate = {"stem": "已审核前候选题：求函数 f(x)=x^2 的导数", "q_type": "blank", "answer": "2x", "knowledge_points": ["MATH-002"]}
    saved = await client.post(f"/api/teacher/resources/{resource_id}/question-candidates", json={"candidates": [candidate]}, headers=_auth(tok))
    assert saved.json()["data"]["review_required"] is True
    candidate_id = saved.json()["data"]["candidates"][0]["candidate_id"]
    async with async_session_factory() as db:
        assert (await db.execute(select(QuestionBank).where(QuestionBank.stem == candidate["stem"]))).scalar_one_or_none() is None
    approved = await client.post(f"/api/teacher/resources/{resource_id}/question-candidates/approve", json={"candidate_ids": [candidate_id]}, headers=_auth(tok))
    assert approved.json()["data"]["review_required"] is False
    async with async_session_factory() as db:
        row = (await db.execute(select(QuestionBank).where(QuestionBank.stem == candidate["stem"]))).scalar_one()
        assert row.source_batch == resource_id
        assert row.annotate_meta["candidate_id"] == candidate_id


@pytest.mark.asyncio
async def test_task_cancel_owned_only(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        other = await make_user(db)
        task = TeacherTask(
            owner_id=tid,
            class_id=None,
            capability="preprocess_course",
            status="queued",
            progress=0,
            payload={"resource_id": "background"},
        )
        db.add(task)
        await db.commit()
        task_id = task.id
    tok = token(tid, "teacher")
    # 其他人看不到/取消不了
    got = await client.get(f"/api/teacher/tasks/{task_id}",
                           headers=_auth(token(other, "teacher")))
    assert got.json()["code"] == 40400
    c = await client.post(f"/api/teacher/tasks/{task_id}/cancel",
                          json={"client_request_id": "cc"}, headers=_auth(tok))
    assert c.json()["data"]["status"] == "cancelled"
