"""M3 教师端：教案/课件/讲解（§5.3）。"""

import io
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models.database import async_session_factory
from app.models.teacher import TeachingArtifact
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
    assert any(li["artifact_id"] == aid for li in lst.json()["data"]["lessons"])
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
async def test_adapt_lesson_builds_editable_topic_plan_and_requires_explicit_slide_confirmation(client):
    """教案必须是可编辑的、按主题和课时确定性生成的草稿。"""
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    auth = _auth(token(tid, "teacher"))
    topic = "导数的概念"
    requirements = "强调图像与导数含义的对应，保留学生板演时间"

    adapted = await client.post(
        "/api/teacher/lessons/adapt",
        json={
            "class_id": str(cid),
            "topic": topic,
            "requirements": requirements,
            "duration_minutes": 60,
        },
        headers=auth,
    )
    assert adapted.status_code == 200, adapted.text
    lesson = adapted.json()["data"]
    assert lesson["status"] == "draft"
    payload = lesson["content"]
    assert payload["topic"] == topic
    assert payload["duration_minutes"] == 60
    assert topic in "\n".join(payload["objectives"])
    assert sum(item["minutes"] for item in payload["timeline"]) == 60
    assert all(
        isinstance(item.get("activities"), list)
        and all(isinstance(activity, str) and activity.strip() for activity in item["activities"])
        for item in payload["timeline"]
    )
    rendered = str(payload)
    assert "不知道" not in rendered
    assert "Exit Ticket" not in rendered
    assert any(requirements in activity for item in payload["timeline"] for activity in item["activities"])

    # 适配只创建 lesson_plan 草稿，绝不隐式生成课件。
    async with async_session_factory() as db:
        artifacts = list(
            (await db.execute(
                select(TeachingArtifact.artifact_type).where(
                    TeachingArtifact.owner_id == tid,
                    TeachingArtifact.class_id == cid,
                )
            )).scalars()
        )
    assert artifacts == ["lesson_plan"]

    lesson_id = lesson["artifact_id"]
    premature = await client.post(
        f"/api/teacher/lessons/{lesson_id}/slides",
        json={"version": 1},
        headers=auth,
    )
    assert premature.status_code == 422
    assert premature.json()["code"] == 42210
    assert premature.json()["message"] == "confirmation_required"

    confirmed = await client.post(
        f"/api/teacher/artifacts/{lesson_id}/confirm",
        json={"client_request_id": "confirm-calculus", "idempotency_key": "confirm-calculus"},
        headers=auth,
    )
    assert confirmed.json()["code"] == 0
    slides = await client.post(
        f"/api/teacher/lessons/{lesson_id}/slides",
        json={"version": 1},
        headers=auth,
    )
    assert slides.json()["code"] == 0, slides.text
    downloaded = await client.get(slides.json()["data"]["content"]["download_url"], headers=auth)
    assert downloaded.status_code == 200
    assert len(downloaded.content) > 1_000
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        slides_xml = [
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        ]
    assert len(slides_xml) >= 2
    assert any(topic in slide_xml for slide_xml in slides_xml)


@pytest.mark.asyncio
async def test_confirmed_lesson_creates_downloadable_pptx(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    auth = _auth(token(tid, "teacher"))
    lesson = await client.post(
        "/api/teacher/lessons/adapt",
        json={"class_id": str(cid), "topic": "函数的单调性", "duration_minutes": 45},
        headers=auth,
    )
    lesson_id = lesson.json()["data"]["artifact_id"]
    confirmed = await client.post(
        f"/api/teacher/artifacts/{lesson_id}/confirm",
        json={"client_request_id": f"confirm-{lesson_id}", "idempotency_key": f"confirm-{lesson_id}"},
        headers=auth,
    )
    assert confirmed.json()["code"] == 0
    slides = await client.post(
        f"/api/teacher/lessons/{lesson_id}/slides",
        json={"version": 1, "style": "简洁课堂"},
        headers=auth,
    )
    assert slides.json()["code"] == 0, slides.text
    data = slides.json()["data"]
    assert data["content"]["download_url"].endswith("/download")
    downloaded = await client.get(data["content"]["download_url"], headers=auth)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )
    assert downloaded.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        slide_parts = [name for name in archive.namelist() if name.startswith("ppt/slides/slide")]
        assert len(slide_parts) >= 2


@pytest.mark.asyncio
async def test_lesson_plan_downloads_as_real_docx(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        await db.commit()
    auth = _auth(token(tid, "teacher"))
    lesson = await client.post(
        "/api/teacher/lessons/adapt",
        json={"class_id": str(cid), "topic": "函数的单调性", "duration_minutes": 45},
        headers=auth,
    )
    lesson_id = lesson.json()["data"]["artifact_id"]

    downloaded = await client.get(
        f"/api/teacher/lessons/{lesson_id}/download", headers=auth
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert downloaded.content[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "函数的单调性" in document_xml


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
    # 造一条真实 active 洞察（按 insight_id 加载，不信任前端摘要）
    async with async_session_factory() as db:
        from app.models.teacher import ActionableInsight

        ins = ActionableInsight(
            class_id=cid, kind="review_backlog", summary="待复核 3 份",
            evidence={"count": 3}, recommended_actions=[{"action": "open_grading", "label": "开始批改"}],
            confidence=0.9,
        )
        db.add(ins)
        await db.commit()
        insight_id = ins.id
    resp = await client.post(
        f"/api/teacher/lessons/{aid}/apply-insight",
        json={"insight_id": str(insight_id), "version": 1},
        headers=_auth(tok),
    )
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["version"] == 2
    # 洞察被标记 applied
    async with async_session_factory() as db:
        ins2 = await db.get(ActionableInsight, insight_id)
        assert ins2.status == "applied"
