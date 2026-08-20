"""M3 教师端：资源/预处理/理解 → 异步任务（§14 / §7.5）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import async_session_factory
from tests._m3_helpers import make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_resource_preprocess_creates_queued_task(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    r = await client.post("/api/teacher/resources/upload",
                          files={"file": ("a.docx", b"content", "application/octet-stream")},
                          headers=_auth(tok))
    assert r.json()["code"] == 0
    assert r.json()["data"]["status"] == "queued"
    # preprocess 引用资源
    p = await client.post("/api/teacher/resources/r001/preprocess",
                          json={"client_request_id": "pp"}, headers=_auth(tok))
    assert p.json()["data"]["capability"] == "preprocess_course"
    assert p.json()["data"]["status"] == "queued"


@pytest.mark.asyncio
async def test_understand_creates_task_and_query(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    u = await client.post("/api/teacher/resources/r002/understand",
                          json={"question": "本文要点", "client_request_id": "ud"},
                          headers=_auth(tok))
    task_id = u.json()["data"]["task_id"]
    assert u.json()["data"]["status"] == "queued"
    # 任务属于该教师可查询
    got = await client.get(f"/api/teacher/tasks/{task_id}", headers=_auth(tok))
    assert got.json()["data"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_task_cancel_owned_only(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        other = await make_user(db)
        await db.commit()
    tok = token(tid, "teacher")
    u = await client.post("/api/teacher/resources/r003/understand",
                          json={"client_request_id": "ud"}, headers=_auth(tok))
    task_id = u.json()["data"]["task_id"]
    # 其他人看不到/取消不了
    got = await client.get(f"/api/teacher/tasks/{task_id}",
                           headers=_auth(token(other, "teacher")))
    assert got.json()["code"] == 40400
    c = await client.post(f"/api/teacher/tasks/{task_id}/cancel",
                          json={"client_request_id": "cc"}, headers=_auth(tok))
    assert c.json()["data"]["status"] == "cancelled"
