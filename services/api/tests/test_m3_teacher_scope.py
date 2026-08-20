"""M3 教师端：teacher role + class_scope 越权（§8 / §19.1）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import async_session_factory
from tests._m3_helpers import add_member, make_class, make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_teacher_owner_accesses_today(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        await db.commit()
    resp = await client.get("/api/teacher/today", headers=_auth(token(tid, "teacher")))
    assert resp.status_code == 200
    assert resp.json()["code"] == 0


@pytest.mark.asyncio
async def test_student_cannot_access_teacher_endpoint(client):
    async with async_session_factory() as db:
        sid = await make_user(db)
        await db.commit()
    resp = await client.get("/api/teacher/today", headers=_auth(token(sid, "student")))
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301  # role_denied


@pytest.mark.asyncio
async def test_other_teacher_cannot_read_class(client):
    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        await db.commit()
    resp = await client.get(
        f"/api/teacher/classes/{cid}/insights", headers=_auth(token(other, "teacher"))
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40302  # class_scope_denied


@pytest.mark.asyncio
async def test_confirmed_member_teacher_can_access(client):
    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        await add_member(db, cid, other, member_role="teacher", confirmed=True)
        await db.commit()
    resp = await client.get(
        f"/api/teacher/classes/{cid}/insights", headers=_auth(token(other, "teacher"))
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unconfirmed_member_denied(client):
    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        await add_member(db, cid, other, member_role="teacher", confirmed=False)
        await db.commit()
    resp = await client.get(
        f"/api/teacher/classes/{cid}/insights", headers=_auth(token(other, "teacher"))
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40302


@pytest.mark.asyncio
async def test_cross_teacher_artifact_uuid_not_found(client):

    from app.domains.teacher.artifacts import create_artifact

    async with async_session_factory() as db:
        owner = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, owner)
        art = await create_artifact(
            db, owner_id=owner, artifact_type="lesson_plan", scene="teacher.prep", class_id=cid,
            payload={"topic": "t"},
        )
        db.add(art)
        await db.commit()
        aid = art.id
    # 其他教师猜测 artifact UUID → not_found（不泄露存在性）
    resp = await client.get(
        f"/api/teacher/artifacts/{aid}", headers=_auth(token(other, "teacher"))
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400
