"""M3 教师端全栈闭环回归测试。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import Base
from app.models.database import async_session_factory
from tests._m3_helpers import add_member, make_class, make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def test_fullstack_schema_contains_daily_user_and_classroom_mode():
    assert "user_id" in Base.metadata.tables["daily_questions"].columns
    assert "classroom_modes" in Base.metadata.tables


@pytest.mark.asyncio
async def test_classroom_mode_survives_process_cache_reset(client, monkeypatch):
    async with async_session_factory() as db:
        teacher_id = await make_user(db)
        student_id = await make_user(db)
        class_id = await make_class(db, teacher_id)
        await add_member(db, class_id, student_id, confirmed=True)
        await db.commit()

    response = await client.post(
        f"/api/teacher/classes/{class_id}/classroom-mode",
        json={
            "enabled": True,
            "lesson_id": None,
            "duration_minutes": 30,
            "client_request_id": f"persist-{class_id}",
            "idempotency_key": f"persist-{class_id}",
        },
        headers=_auth(token(teacher_id, "teacher")),
    )
    assert response.json()["code"] == 0

    import app.domains.teacher.classroom as classroom

    monkeypatch.setattr(classroom, "_CLASSROOM_STATE", {}, raising=False)
    persisted = await client.get(
        f"/api/classes/{class_id}/classroom-mode",
        headers=_auth(token(student_id, "student")),
    )
    assert persisted.json()["code"] == 0
    assert persisted.json()["data"]["enabled"] is True

