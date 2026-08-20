"""M3 教师端：教案/课件/讲解（§5.3）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import async_session_factory
from tests._m3_helpers import make_class, make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_adapt_lesson_creates_draft(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    resp = await client.post(
        "/api/teacher/lessons/adapt",
        json={"class_id": str(cid), "topic": "函数的单调性", "requirements": "精简讲授",
              "duration_minutes": 45},
        headers=_auth(token(tid, "teacher")),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "draft"
    assert "__art" and data["artifact_id"]


@pytest.mark.asyncio
async def test_lesson_list_and_get(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    tok = token(tid, "teacher")
    r1 = await client.post("/api/teacher/lessons/adapt",
                           json={"class_id": str(cid), "topic": "导数"}, headers=_auth(tok))
    aid = r1.json()["data"]["artifact_id"]
    lst = await client.get(f"/api/teacher/lessons?class_id={cid}", headers=_auth(tok))
    assert any(li["lesson_id"] == aid for li in lst.json()["data"]["lessons"])
    got = await client.get(f"/api/teacher/lessons/{aid}", headers=_auth(tok))
    assert got.json()["data"]["lesson_id"] == aid


@pytest.mark.asyncio
async def test_create_slides_requires_confirmed_lesson(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    tok = token(tid, "teacher")
    r1 = await client.post("/api/teacher/lessons/adapt",
                           json={"class_id": str(cid), "topic": "导数"}, headers=_auth(tok))
    aid = r1.json()["data"]["artifact_id"]
    # draft 未确认 → 42210
    resp = await client.post(f"/api/teacher/lessons/{aid}/slides",
                             json={"version": 1}, headers=_auth(tok))
    assert resp.json()["code"] == 42210


@pytest.mark.asyncio
async def test_apply_insight_creates_new_version(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    tok = token(tid, "teacher")
    r1 = await client.post("/api/teacher/lessons/adapt",
                           json={"class_id": str(cid), "topic": "导数"}, headers=_auth(tok))
    # 先确认以触发新版本
    aid = r1.json()["data"]["artifact_id"]
    await client.post(f"/api/teacher/artifacts/{aid}/confirm",
                      json={"client_request_id": "x", "idempotency_key": "conf"}, headers=_auth(tok))
    resp = await client.post(
        f"/api/teacher/lessons/{aid}/apply-insight",
        json={"insight_id": "00000000-0000-0000-0000-000000000000", "version": 1},
        headers=_auth(tok),
    )
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["version"] == 2
