"""M3 教师端：题集/作业流程（§12）。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.database import async_session_factory
from app.models.question_bank import QuestionBank, stem_hash
from tests._m3_helpers import make_class, make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _seed_bank(count: int = 3):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        tag = uuid.uuid4().hex[:8]
        for i in range(count):
            stem = f"{tag}题干{i} 求导 f(x)={i}"
            db.add(QuestionBank(
                stem=stem, q_type="solution", answer=f"答案{i}",
                difficulty="medium", kp_codes=["MATH-002"], scope="student",
                hash=stem_hash(stem),
            ))
        await db.commit()
        return tid, cid


async def _make_confirmed_quiz(client, tok, cid) -> str:
    g = await client.post("/api/teacher/quizzes/generate",
                          json={"class_id": str(cid), "knowledge_points": ["MATH-002"],
                                "count": 3, "question_types": {"choice": 0, "blank": 0, "text": 3}},
                          headers=_auth(tok))
    assert g.json()["code"] == 0, g.text
    aid = g.json()["data"]["artifact_id"]
    await client.post(f"/api/teacher/artifacts/{aid}/confirm",
                      json={"client_request_id": "q", "idempotency_key": "qc"}, headers=_auth(tok))
    return aid


@pytest.mark.asyncio
async def test_generate_quiz_creates_draft_artifact(client):
    tid, cid = await _seed_bank(3)
    g = await client.post("/api/teacher/quizzes/generate",
                          json={"class_id": str(cid), "knowledge_points": ["MATH-002"],
                                "count": 3, "question_types": {"choice": 0, "blank": 0, "text": 3}},
                          headers=_auth(token(tid, "teacher")))
    assert g.json()["code"] == 0
    data = g.json()["data"]
    assert data["status"] == "draft"
    assert len(data["content"]["items"]) == 3


@pytest.mark.asyncio
async def test_generate_quiz_insufficient_fails(client):
    tid, cid = await _seed_bank(1)
    g = await client.post("/api/teacher/quizzes/generate",
                          json={"class_id": str(cid), "knowledge_points": ["MATH-002"],
                                "count": 5, "question_types": {"choice": 0, "blank": 0, "text": 5}},
                          headers=_auth(token(tid, "teacher")))
    assert g.json()["code"] == 40001
    assert g.json()["message"] == "insufficient_questions"


@pytest.mark.asyncio
async def test_new_assignment_is_draft_and_publish(client):
    tid, cid = await _seed_bank(3)
    tok = token(tid, "teacher")
    aid = await _make_confirmed_quiz(client, tok, cid)
    # 未确认不可建？已确认；创建 assignment draft
    r = await client.post("/api/teacher/assignments",
                          json={"class_id": str(cid), "title": "周测", "artifact_id": aid,
                                "client_assignment_id": "ca-1"},
                          headers=_auth(tok))
    assert r.json()["code"] == 0
    a = r.json()["data"]
    assert a["status"] == "draft"
    # 班级定向已写入：学生端 /api/student/assignments 依赖 assignment_targets
    async with async_session_factory() as db:
        from sqlalchemy import select as sel

        from app.models.coursework import AssignmentTarget

        targets = (
            await db.execute(
                sel(AssignmentTarget).where(
                    AssignmentTarget.assignment_id == uuid.UUID(a["assignment_id"]),
                    AssignmentTarget.target_type == "class",
                )
            )
        ).scalars().all()
    assert len(targets) >= 1, "发布作业必须定向班级（学生联动可见性）"
    # 幂等：同 client_assignment_id
    r2 = await client.post("/api/teacher/assignments",
                           json={"class_id": str(cid), "title": "周测", "artifact_id": aid,
                                 "client_assignment_id": "ca-1"},
                           headers=_auth(tok))
    assert r2.json()["data"]["assignment_id"] == a["assignment_id"]
    assert r2.json()["data"]["replayed"] is True
    # publish
    p = await client.post(f"/api/teacher/assignments/{a['assignment_id']}/publish",
                          json={"client_request_id": "p1", "idempotency_key": "pk"}, headers=_auth(tok))
    assert p.json()["data"]["status"] == "published"


@pytest.mark.asyncio
async def test_create_assignment_requires_confirmed_quiz(client):
    tid, cid = await _seed_bank(3)
    tok = token(tid, "teacher")
    # 生成但未确认的 quiz_set artifact
    g = await client.post("/api/teacher/quizzes/generate",
                          json={"class_id": str(cid), "knowledge_points": ["MATH-002"],
                                "count": 3, "question_types": {"choice": 0, "blank": 0, "text": 3}},
                          headers=_auth(tok))
    aid = g.json()["data"]["artifact_id"]
    r = await client.post("/api/teacher/assignments",
                          json={"class_id": str(cid), "title": "未确认", "artifact_id": aid,
                                "client_assignment_id": "ca-2"},
                          headers=_auth(tok))
    assert r.json()["code"] == 42210
