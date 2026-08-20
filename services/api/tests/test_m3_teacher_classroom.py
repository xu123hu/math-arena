"""M3 教师端：课堂模式 + 视频洞察（§14）。"""

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
async def test_classroom_mode_enable_and_audit(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    tok = token(tid, "teacher")
    r = await client.post(f"/api/teacher/classes/{cid}/classroom-mode",
                          json={"enabled": True, "lesson_id": None, "duration_minutes": 45,
                                "client_request_id": "cm", "idempotency_key": "cmk"},
                          headers=_auth(tok))
    assert r.json()["code"] == 0
    assert r.json()["data"]["enabled"] is True
    # 审计写入
    async with async_session_factory() as db:
        from sqlalchemy import select

        from app.models.teacher import TeacherAction

        acts = (await db.execute(select(TeacherAction))).scalars().all()
    assert any(a.action_type == "classroom.mode.set" for a in acts)


@pytest.mark.asyncio
async def test_classroom_mode_denied_for_non_teacher_class(client):
    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        await db.commit()
    r = await client.post(f"/api/teacher/classes/{cid}/classroom-mode",
                          json={"enabled": True, "lesson_id": None, "client_request_id": "x",
                                "idempotency_key": "k"},
                          headers=_auth(token(other, "teacher")))
    assert r.json()["code"] == 40302


@pytest.mark.asyncio
async def test_video_insights_degraded(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    r = await client.get(f"/api/teacher/classes/{cid}/video-insights",
                         headers=_auth(token(tid, "teacher")))
    assert r.json()["data"]["degraded"] is True
