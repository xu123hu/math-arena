"""M3 教师端：预批改与正式计分（§13）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.coursework import Assignment, Quiz, QuizItem, Submission, SubmissionItem
from app.models.database import async_session_factory
from app.models.file import File
from tests._m3_helpers import make_class, make_user, token


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


async def _seed_item():
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        a = Assignment(class_id=cid, creator_id=tid, title="作业", type="quiz", status="published")
        db.add(a)
        await db.flush()
        s = Submission(user_id=tid, assignment_id=a.id, client_submit_id="s1", status="pending_review")
        db.add(s)
        await db.flush()
        it = SubmissionItem(submission_id=s.id, item_no=1, q_type="text", verdict="pending_review",
                            answer_text="作答")
        db.add(it)
        await db.commit()
        return tid, cid, it.id


async def _seed_objective_item(
    *, answer_text: str, standard_answer: str, include_quiz_item: bool = True
):
    """Persisted quiz context is the only evidence for objective scoring."""
    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        quiz = Quiz(user_id=tid, source="assignment", title="函数测验", kp_codes=["MATH-003"])
        db.add(quiz)
        await db.flush()
        if include_quiz_item:
            db.add(
                QuizItem(
                    quiz_id=quiz.id,
                    item_no=1,
                    q_type="choice",
                    question_text="函数 f(x)=x^2 的最小值是？",
                    options={"A": "-1", "B": "0", "C": "1"},
                    answer=standard_answer,
                    answer_analysis="因为 x^2 ≥ 0，所以最小值为 0。",
                    kp_code="MATH-003",
                )
            )
        assignment = Assignment(
            class_id=cid,
            creator_id=tid,
            title="二次函数随堂作业",
            type="quiz",
            quiz_id=quiz.id,
            status="published",
        )
        db.add(assignment)
        await db.flush()
        submission = Submission(
            user_id=tid,
            quiz_id=quiz.id,
            assignment_id=assignment.id,
            client_submit_id=f"objective-{answer_text}-{standard_answer}",
            status="pending_review",
        )
        db.add(submission)
        await db.flush()
        item = SubmissionItem(
            submission_id=submission.id,
            item_no=1,
            q_type="choice",
            verdict="pending_review",
            answer_text=answer_text,
        )
        db.add(item)
        await db.commit()
        return tid, cid, item.id


@pytest.mark.asyncio
async def test_objective_suggestion_uses_persisted_standard_answer_and_exposes_context(client):
    teacher_id, class_id, wrong_item_id = await _seed_objective_item(
        answer_text="A", standard_answer="B"
    )
    correct_teacher_id, correct_class_id, correct_item_id = await _seed_objective_item(
        answer_text=" b ", standard_answer="B"
    )
    missing_teacher_id, missing_class_id, missing_answer_item_id = await _seed_objective_item(
        answer_text="B", standard_answer=""
    )
    no_context_teacher_id, no_context_class_id, no_context_item_id = await _seed_objective_item(
        answer_text="B", standard_answer="B", include_quiz_item=False
    )
    headers = _auth(token(teacher_id, "teacher"))

    wrong = await client.post(
        f"/api/teacher/grading/{wrong_item_id}/suggest",
        json={"class_id": str(class_id), "client_request_id": "wrong-choice"},
        headers=headers,
    )
    assert wrong.json()["data"]["suggestion_score"] == 0.0
    assert wrong.json()["data"]["confidence"] >= 0.9
    assert wrong.json()["data"]["review_needed"] is False

    correct = await client.post(
        f"/api/teacher/grading/{correct_item_id}/suggest",
        json={"class_id": str(correct_class_id), "client_request_id": "correct-choice"},
        headers=_auth(token(correct_teacher_id, "teacher")),
    )
    assert correct.json()["data"]["suggestion_score"] == 1.0
    assert correct.json()["data"]["confidence"] >= 0.9
    assert correct.json()["data"]["review_needed"] is False

    missing = await client.post(
        f"/api/teacher/grading/{missing_answer_item_id}/suggest",
        json={"class_id": str(missing_class_id), "client_request_id": "missing-standard"},
        headers=_auth(token(missing_teacher_id, "teacher")),
    )
    assert missing.json()["data"]["review_needed"] is True
    assert "缺少标准答案" in missing.json()["data"]["evidence"]

    no_context = await client.post(
        f"/api/teacher/grading/{no_context_item_id}/suggest",
        json={"class_id": str(no_context_class_id), "client_request_id": "missing-context"},
        headers=_auth(token(no_context_teacher_id, "teacher")),
    )
    assert no_context.json()["data"]["review_needed"] is True
    assert "缺少已持久化题目上下文" in no_context.json()["data"]["evidence"]

    detail = await client.get(
        f"/api/teacher/grading/{wrong_item_id}?class_id={class_id}", headers=headers
    )
    data = detail.json()["data"]
    assert data["assignment_title"] == "二次函数随堂作业"
    assert data["question_text"] == "函数 f(x)=x^2 的最小值是？"
    assert data["question_type"] == "choice"
    assert data["options"] == {"A": "-1", "B": "0", "C": "1"}
    assert data["standard_answer"] == "B"
    assert data["answer_analysis"] == "因为 x^2 ≥ 0，所以最小值为 0。"


@pytest.mark.asyncio
async def test_suggest_does_not_write_final_score(client):
    tid, cid, item_id = await _seed_item()
    tok = token(tid, "teacher")
    r = await client.post(f"/api/teacher/grading/{item_id}/suggest",
                          json={"class_id": str(cid), "client_request_id": "sg"},
                          headers=_auth(tok))
    assert r.json()["code"] == 0
    data = r.json()["data"]
    assert data["decision"] == "draft"
    # 建议不写正式分：teacher_final_score 仍为空
    assert data["teacher_final_score"] is None
    detail = await client.get(f"/api/teacher/grading/{item_id}?class_id={cid}", headers=_auth(tok))
    body = detail.json()["data"]
    assert body["suggestion"]["suggestion_score"] is not None
    assert body["teacher_final_score"] is None


@pytest.mark.asyncio
async def test_detail_auto_suggestion_can_be_confirmed(client):
    tid, cid, item_id = await _seed_item()
    tok = token(tid, "teacher")

    detail = await client.get(
        f"/api/teacher/grading/{item_id}?class_id={cid}", headers=_auth(tok)
    )
    assert detail.json()["code"] == 0, detail.text
    suggestion = detail.json()["data"]["suggestion"]
    assert suggestion["suggestion_id"]

    confirmed = await client.post(
        f"/api/teacher/grading/{item_id}/confirm",
        json={
            "suggestion_id": suggestion["suggestion_id"],
            "decision": "accept",
            "teacher_feedback": "已复核",
            "version": suggestion["version"],
        },
        headers={**_auth(tok), "Idempotency-Key": f"auto-confirm:{item_id}"},
    )
    assert confirmed.json()["code"] == 0, confirmed.text
    assert confirmed.json()["data"]["decision"] == "accepted"


@pytest.mark.asyncio
async def test_teacher_can_view_photo_for_scoped_grading_item(client):
    from app.domains.files.router import _local_file_path

    async with async_session_factory() as db:
        tid = await make_user(db)
        cid = await make_class(db, tid)
        assignment = Assignment(class_id=cid, creator_id=tid, title="拍照作业", type="quiz", status="published")
        db.add(assignment)
        await db.flush()
        submission = Submission(user_id=tid, assignment_id=assignment.id, client_submit_id="photo-grade")
        db.add(submission)
        photo = File(
            user_id=tid,
            filename="solution.png",
            file_type="image",
            mime="image/png",
            size_bytes=12,
            sha256="3" * 64,
            storage_uri="local:test-photo-token",
            status="parsed",
        )
        db.add(photo)
        await db.flush()
        item = SubmissionItem(
            submission_id=submission.id,
            item_no=1,
            q_type="solution",
            verdict="pending_review",
            file_id=photo.id,
        )
        db.add(item)
        await db.commit()
        path = _local_file_path(photo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"photo-bytes!")
        item_id = item.id

    response = await client.get(
        f"/api/teacher/grading/{item_id}/file",
        headers=_auth(token(tid, "teacher")),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"photo-bytes!"


@pytest.mark.asyncio
async def test_confirm_accept_sets_final_and_idempotent(client):
    tid, cid, item_id = await _seed_item()
    tok = token(tid, "teacher")
    sg = await client.post(f"/api/teacher/grading/{item_id}/suggest",
                           json={"class_id": str(cid), "client_request_id": "sg"},
                           headers=_auth(tok))
    suggestion_id = sg.json()["data"]["suggestion_id"]
    r1 = await client.post(f"/api/teacher/grading/{item_id}/confirm",
                           json={"suggestion_id": suggestion_id, "decision": "accept",
                                 "teacher_feedback": "ok", "version": 1},
                           headers={**_auth(tok), "Idempotency-Key": "gk"},
                           )
    assert r1.json()["code"] == 0, r1.text
    assert r1.json()["data"]["decision"] == "accepted"
    r2 = await client.post(f"/api/teacher/grading/{item_id}/confirm",
                           json={"suggestion_id": suggestion_id, "decision": "accept", "version": 1},
                           headers={**_auth(tok), "Idempotency-Key": "gk"},
                           )
    assert r2.json()["data"]["replayed"] is True


@pytest.mark.asyncio
async def test_confirm_override_saves_both(client):
    tid, cid, item_id = await _seed_item()
    tok = token(tid, "teacher")
    sg = await client.post(f"/api/teacher/grading/{item_id}/suggest",
                           json={"class_id": str(cid), "client_request_id": "sg"},
                           headers=_auth(tok))
    suggestion_id = sg.json()["data"]["suggestion_id"]
    r = await client.post(f"/api/teacher/grading/{item_id}/confirm",
                          json={"suggestion_id": suggestion_id, "decision": "override",
                                "final_score": 7.5, "teacher_feedback": "补充分", "version": 1},
                          headers={**_auth(tok), "Idempotency-Key": "gk2"},
                          )
    data = r.json()["data"]
    assert data["teacher_final_score"] == 7.5
    assert data["decision"] == "overridden"
    detail = await client.get(f"/api/teacher/grading/{item_id}?class_id={cid}", headers=_auth(tok))
    assert detail.json()["data"]["suggestion"]["decision"] == "overridden"


@pytest.mark.asyncio
async def test_confirm_requires_teacher_in_class(client):
    async with async_session_factory() as db:
        tid = await make_user(db)
        other = await make_user(db)
        cid = await make_class(db, tid)
        a = Assignment(class_id=cid, creator_id=tid, title="作业", type="quiz", status="published")
        db.add(a)
        await db.flush()
        s = Submission(user_id=tid, assignment_id=a.id, client_submit_id="s2")
        db.add(s)
        await db.flush()
        it = SubmissionItem(submission_id=s.id, item_no=1, q_type="text", verdict="pending_review")
        db.add(it)
        await db.commit()
        item_id = it.id
    r = await client.post(f"/api/teacher/grading/{item_id}/suggest",
                          json={"class_id": str(cid), "client_request_id": "sg"},
                          headers=_auth(token(other, "teacher")))
    assert r.status_code == 403
    assert r.json()["code"] == 40302
