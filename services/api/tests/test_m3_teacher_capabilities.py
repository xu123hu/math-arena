"""M3 教师端：Capability Gateway（§10.4 / §16）。"""

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
async def test_capability_adapt_lesson_creates_artifact(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    r = await client.post(
        "/api/teacher/capabilities/adapt_lesson",
        json={"scene": "teacher.prep", "class_id": str(cid),
              "payload": {"topic": "函数", "requirements": "精简"},
              "client_request_id": "cap"},
        headers=_auth(token(tid, "teacher")),
    )
    assert r.json()["code"] == 0, r.text
    data = r.json()["data"]
    assert data["status"] == "draft"
    assert data["artifact_id"]


@pytest.mark.asyncio
async def test_capability_requires_teacher_role(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    r = await client.post(
        "/api/teacher/capabilities/adapt_lesson",
        json={"scene": "teacher.prep", "class_id": str(cid), "payload": {"topic": "t"},
              "client_request_id": "cap"},
        headers=_auth(token(tid, "student")),
    )
    assert r.json()["code"] == 40301


@pytest.mark.asyncio
async def test_capabilities_list_excludes_research(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    r = await client.get("/api/teacher/capabilities", headers=_auth(token(tid, "teacher")))
    caps = set(r.json()["data"]["capabilities"])
    assert {"adapt_lesson", "create_slides", "create_quiz", "suggest_grade",
            "explain_problem", "preprocess_course", "understand_document"} <= caps
    assert "review_paper" not in caps


@pytest.mark.asyncio
async def test_capability_rejects_invalid_scene(client):
    """审计 C-02：拒绝任意 scene（不在教师 Scene 白名单）。"""
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    r = await client.post(
        "/api/teacher/capabilities/adapt_lesson",
        json={"scene": "student.chat", "class_id": str(cid), "payload": {"topic": "t"},
              "client_request_id": "cap"},
        headers=_auth(token(tid, "teacher")),
    )
    assert r.json()["code"] == 40001
    assert r.json()["message"] == "invalid_scene"


@pytest.mark.asyncio
async def test_capability_rejects_foreign_class(client):
    """审计 C-02：class scope 强制（他班 class_id 拒绝）。"""
    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        await db.commit()
    r = await client.post(
        "/api/teacher/capabilities/adapt_lesson",
        json={"scene": "teacher.prep", "class_id": str(cid), "payload": {"topic": "t"},
              "client_request_id": "cap"},
        headers=_auth(token(other, "teacher")),
    )
    assert r.json()["code"] == 40302


@pytest.mark.asyncio
async def test_capability_rejects_unknown_capability(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    r = await client.post(
        "/api/teacher/capabilities/review_paper",
        json={"scene": "teacher.prep", "payload": {}, "client_request_id": "cap"},
        headers=_auth(token(tid, "teacher")),
    )
    assert r.json()["code"] == 40001
    assert r.json()["message"] == "unknown_capability"
