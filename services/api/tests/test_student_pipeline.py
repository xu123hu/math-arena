"""学生端管线真实性测试（G4）

覆盖：
1. choice/judge 判分（与 quiz_items 标准答案真实比对）
2. blank 判分（mock sandbox check_equivalence 四层兜底接线）
3. solution AI 初批 JSON 解析、错因枚举校验与 LLM 降级
4. mastery（BKT-lite）/ streak upsert
5. 题组真实生成（mock LLM 返回合法 JSON → QuizItem 落库；失败 → 明确错误）
6. practice/submit 端到端：聚合分数 + mastery/streak/错题 落库

需要 PostgreSQL + Redis 运行中（与 test_api_integration 同环境）。
DB 会话在测试函数内创建（pyproject: asyncio_default_fixture_loop_scope=session，
fixture 与测试不同事件循环，不能跨 fixture 持有连接，与 test_m1_fixes 同模式）。
"""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.gateway import student_router as sr
from app.main import app
from app.models.coursework import (
    DailyQuestion,
    ErrorRecord,
    MasteryRecord,
    Quiz,
    QuizItem,
    Streak,
    Submission,
)
from app.models.database import get_db
from app.models.knowledge_point import KnowledgePoint
from app.models.user import User

_test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_test_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_get_db():
    async with _test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = _override_get_db


@asynccontextmanager
async def _db():
    """函数级 DB 会话：函数级测试不 commit，结束 rollback 保持库干净"""
    async with _test_session_factory() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_test_kps():
    """自清洁：删除本文件测试种下的 TST 前缀 KP 及关联行（mastery/error），
    保证全量跑完 pytest 后 knowledge_points 不新增非 MATH- 前缀行"""
    yield
    async with _test_session_factory() as s:
        kp_ids = select(KnowledgePoint.id).where(KnowledgePoint.code.like("TST%"))
        await s.execute(delete(MasteryRecord).where(MasteryRecord.kp_id.in_(kp_ids)))
        await s.execute(delete(ErrorRecord).where(ErrorRecord.kp_code.like("TST%")))
        await s.execute(delete(KnowledgePoint).where(KnowledgePoint.code.like("TST%")))
        await s.commit()


# ========== 辅助 ==========


async def _make_user(session) -> User:
    user = User(phone=f"139{uuid.uuid4().int % 100000000:08d}", nickname="")
    session.add(user)
    await session.flush()
    return user


async def _make_kp(session, code: str | None = None) -> KnowledgePoint:
    code = code or f"TST_t_{uuid.uuid4().hex[:10]}"  # TST 前缀：autouse fixture 自清洁
    kp = KnowledgePoint(code=code, name=f"测试知识点{code}")
    session.add(kp)
    await session.flush()
    return kp


async def _make_quiz_item(
    session,
    user: User,
    kp_code: str,
    *,
    q_type: str = "choice",
    answer: str = "B",
    item_no: int = 1,
    quiz: Quiz | None = None,
) -> tuple[Quiz, QuizItem]:
    if quiz is None:
        quiz = Quiz(user_id=user.id, source="ai_generated", title="t", kp_codes=[kp_code])
        session.add(quiz)
        await session.flush()
    item = QuizItem(
        quiz_id=quiz.id,
        item_no=item_no,
        q_type=q_type,
        question_text="测试题干 $1+1=?$",
        answer=answer,
        answer_analysis="解析",
        kp_code=kp_code,
    )
    session.add(item)
    await session.flush()
    return quiz, item


def _mock_llm_router(payload: dict | None = None, *, raw: str | None = None, raises: bool = False):
    """构造 mock ModelRouter：chat 返回合法 JSON / 原始串 / 抛异常"""
    router = AsyncMock()
    if raises:
        router.chat.side_effect = RuntimeError("All model providers failed")
    elif raw is not None:
        router.chat.return_value = {"content": raw}
    else:
        router.chat.return_value = {"content": json.dumps(payload, ensure_ascii=False)}
    return router


# ========== 1. choice/judge 判分 ==========


class TestChoiceGrading:
    async def test_choice_correct(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, answer="B")
            verdict, score, _ = await sr._grade_item(db, item, "choice", "B")
            assert verdict == "correct"
            assert score == 10.0

    async def test_choice_wrong(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, answer="B")
            verdict, score, _ = await sr._grade_item(db, item, "choice", "C")
            assert verdict == "wrong"
            assert score == 0.0

    async def test_choice_answer_with_text_prefix(self):
        """标答为 'B. $2$' 时，学生答 'B' 也算对"""
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, answer="B. $2$")
            verdict, score, _ = await sr._grade_item(db, item, "choice", "b")
            assert verdict == "correct"
            assert score == 10.0

    async def test_choice_no_reference_pending_review(self):
        """题组外作答（无标答）→ 待人工，不造假分"""
        async with _db() as db:
            verdict, score, _ = await sr._grade_item(db, None, "choice", "A")
            assert verdict == "pending_review"
            assert score is None

    async def test_judge_grading(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, q_type="judge", answer="正确")
            verdict, _, _ = await sr._grade_item(db, item, "judge", "正确")
            assert verdict == "correct"
            verdict, _, _ = await sr._grade_item(db, item, "judge", "错误")
            assert verdict == "wrong"


# ========== 2. blank 判分（mock sandbox） ==========


class TestBlankGrading:
    async def test_blank_correct(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, q_type="blank", answer="x+1")
            with patch.object(
                sr, "check_equivalence",
                new=AsyncMock(return_value={"verdict": "correct", "method": "symbolic_equiv"}),
            ) as mock_eq:
                verdict, score, extra = await sr._grade_item(db, item, "blank", "1+x")
            assert verdict == "correct"
            assert score == 10.0
            assert extra["method"] == "symbolic_equiv"
            mock_eq.assert_awaited_once_with("1+x", "x+1")

    async def test_blank_wrong(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, q_type="blank", answer="x+1")
            with patch.object(
                sr, "check_equivalence",
                new=AsyncMock(return_value={"verdict": "wrong", "method": "symbolic_diff"}),
            ):
                verdict, score, _ = await sr._grade_item(db, item, "blank", "x+2")
            assert verdict == "wrong"
            assert score == 0.0

    async def test_blank_pending_review(self):
        """沙箱超时/解析失败 → pending_review 待人工"""
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, q_type="blank", answer="x+1")
            with patch.object(
                sr, "check_equivalence",
                new=AsyncMock(return_value={"verdict": "pending_review", "method": "timeout"}),
            ):
                verdict, score, _ = await sr._grade_item(db, item, "blank", "sqrt(x)")
            assert verdict == "pending_review"
            assert score is None

    async def test_blank_empty_answer_wrong(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(db, user, kp.code, q_type="blank", answer="x+1")
            verdict, score, _ = await sr._grade_item(db, item, "blank", None)
            assert verdict == "wrong"
            assert score == 0.0


# ========== 3. solution AI 初批 ==========


class TestSolutionPregrade:
    async def _grade(self, db, router, answer_text="解：……"):
        user = await _make_user(db)
        kp = await _make_kp(db)
        _, item = await _make_quiz_item(
            db, user, kp.code, q_type="solution", answer="解：$x=2$"
        )
        with patch.object(sr, "get_model_router", return_value=router):
            return await sr._grade_item(db, item, "solution", answer_text)

    async def test_ai_pregrade_json_parsed(self):
        async with _db() as db:
            router = _mock_llm_router({
                "score": 8, "max_score": 10,
                "comment": "思路正确，最后一步计算出错", "error_type": "calculation",
            })
            verdict, score, extra = await self._grade(db, router)
            assert verdict == "pending_review"  # AI 初批留痕，待教师确认
            assert score == 8.0
            assert extra["ai_pregraded"] is True
            assert extra["error_type"] == "calculation"
            assert "计算" in extra["comment"]

    async def test_ai_pregrade_invalid_error_type_nulled(self):
        """error_type 非五枚举 → 归 null"""
        async with _db() as db:
            router = _mock_llm_router({"score": 5, "max_score": 10, "comment": "x", "error_type": "weird"})
            _, _, extra = await self._grade(db, router)
            assert extra["error_type"] is None

    async def test_ai_pregrade_score_clamped(self):
        """score 超过 max_score → clamp"""
        async with _db() as db:
            router = _mock_llm_router({"score": 99, "max_score": 10, "comment": "", "error_type": None})
            _, score, _ = await self._grade(db, router)
            assert score == 10.0

    async def test_ai_pregrade_llm_down_degrades(self):
        """LLM 不可用 → pending_review 占位 + degraded 注明"""
        async with _db() as db:
            router = _mock_llm_router(raises=True)
            verdict, score, extra = await self._grade(db, router)
            assert verdict == "pending_review"
            assert score is None
            assert extra["degraded"] == "llm_unavailable"

    async def test_ai_pregrade_bad_json_degrades(self):
        async with _db() as db:
            router = _mock_llm_router(raw="我无法评阅这道题")
            verdict, score, extra = await self._grade(db, router)
            assert verdict == "pending_review"
            assert score is None
            assert extra["degraded"] == "llm_unavailable"

    async def test_solution_empty_answer_wrong(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            _, item = await _make_quiz_item(
                db, user, kp.code, q_type="solution", answer="解：$x=2$"
            )
            verdict, score, _ = await sr._grade_item(db, item, "solution", None)
            assert verdict == "wrong"
            assert score == 0.0


# ========== 4. mastery / streak ==========


class TestMasteryStreak:
    async def test_mastery_correct_then_wrong(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)

            await sr._update_mastery(db, user.id, kp.code, correct=True, hint_count=0)
            mr = await db.get(MasteryRecord, (user.id, kp.id))
            assert mr is not None
            assert mr.practice_count == 1
            assert mr.correct_count == 1
            m1 = float(mr.mastery)
            assert m1 > 0.5  # 对的题 +

            await sr._update_mastery(db, user.id, kp.code, correct=False, hint_count=2)
            await db.flush()
            mr = await db.get(MasteryRecord, (user.id, kp.id))
            assert float(mr.mastery) < m1  # 错的题 -
            assert mr.practice_count == 2
            assert mr.correct_count == 1
            assert mr.hint_count == 2
            assert mr.last_practiced_at is not None

    async def test_mastery_clamped(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            for _ in range(50):
                await sr._update_mastery(db, user.id, kp.code, correct=True)
            mr = await db.get(MasteryRecord, (user.id, kp.id))
            assert 0.0 <= float(mr.mastery) <= 1.0

    async def test_mastery_unknown_kp_skipped(self):
        async with _db() as db:
            user = await _make_user(db)
            # 知识点未入库 → 不写孤儿记录，也不抛错
            await sr._update_mastery(db, user.id, f"no_such_{uuid.uuid4().hex[:8]}", correct=True)

    async def test_streak_upsert_flow(self):
        async with _db() as db:
            user = await _make_user(db)
            today = date.today()

            await sr._upsert_streak(db, user.id)
            streak = await db.get(Streak, user.id)
            assert streak.current_streak == 1
            assert streak.longest_streak == 1
            assert streak.last_active_date == today

            # 当日重复提交不累计
            await sr._upsert_streak(db, user.id)
            await db.flush()
            assert streak.current_streak == 1

            # 昨天已打卡 → 连续 +1
            streak.last_active_date = today - timedelta(days=1)
            await db.flush()
            await sr._upsert_streak(db, user.id)
            await db.flush()
            assert streak.current_streak == 2
            assert streak.longest_streak == 2

            # 断签 → 重置为 1
            streak.last_active_date = today - timedelta(days=5)
            await db.flush()
            await sr._upsert_streak(db, user.id)
            await db.flush()
            assert streak.current_streak == 1
            assert streak.longest_streak == 2  # 最长纪录保留


# ========== 5. 题组真实生成 ==========


def _quiz_payload(kp_code: str, q_type: str = "choice") -> dict:
    return {
        "q_type": q_type,
        "question_text": "函数 $f(x)=x^2$ 的导数是？",
        "options": ["A. $2x$", "B. $x$", "C. $x^2$", "D. $2$"],
        "answer": "A",
        "answer_analysis": "由幂函数求导 [[STEP]] 得 $2x$",
        "kp_codes": [kp_code],
        "difficulty": "medium",
    }


class TestQuizGeneration:
    async def test_special_quiz_items_persisted(self):
        """mock LLM 返回合法 JSON → 3 个 QuizItem 落库（题干/选项/答案/解析/知识点）"""
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            router = _mock_llm_router(_quiz_payload(kp.code))
            with patch.object(sr, "get_model_router", return_value=router):
                quiz_id = await sr._generate_special_quiz(db, user.id, kp.code)

            items = (
                (await db.execute(
                    select(QuizItem).where(QuizItem.quiz_id == quiz_id).order_by(QuizItem.item_no)
                )).scalars().all()
            )
            assert len(items) == 3
            assert router.chat.await_count == 3
            for it in items:
                assert it.question_text
                assert it.answer == "A"
                assert it.answer_analysis
                assert it.kp_code == kp.code
                assert it.ai_generated is True
            # options 由 list 归一化为 dict
            assert items[0].options == {"A": "A. $2x$", "B": "B. $x$", "C": "C. $x^2$", "D": "D. $2$"}

    async def test_special_quiz_llm_failure_raises(self):
        """LLM 不可用 → QuizGenerationError（不产空题组）"""
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            router = _mock_llm_router(raises=True)
            with (
                patch.object(sr, "get_model_router", return_value=router),
                pytest.raises(sr.QuizGenerationError),
            ):
                await sr._generate_special_quiz(db, user.id, kp.code)

    async def test_special_quiz_bad_json_raises(self):
        async with _db() as db:
            user = await _make_user(db)
            kp = await _make_kp(db)
            router = _mock_llm_router(raw="这不是 JSON")
            with (
                patch.object(sr, "get_model_router", return_value=router),
                pytest.raises(sr.QuizGenerationError),
            ):
                await sr._generate_special_quiz(db, user.id, kp.code)

    async def test_retry_quiz_without_errors_raises(self):
        """无错题记录 → 明确错误"""
        async with _db() as db:
            user = await _make_user(db)
            with pytest.raises(sr.QuizGenerationError):
                await sr._generate_retry_quiz(db, user.id)

    async def test_daily_quiz_generates_item_and_row(self):
        """每日一题：真实生成 1 题 + 落 daily_questions"""
        async with _db() as db:
            user = await _make_user(db)
            router = _mock_llm_router(_quiz_payload("function"))
            with patch.object(sr, "get_model_router", return_value=router):
                quiz_id = await sr._generate_daily_quiz(db, user.id)
            items = (
                (await db.execute(select(QuizItem).where(QuizItem.quiz_id == quiz_id))).scalars().all()
            )
            assert len(items) == 1
            daily = (
                await db.execute(select(DailyQuestion).where(DailyQuestion.date == date.today()))
            ).scalar_one_or_none()
            assert daily is not None
            assert daily.quiz_id == quiz_id


# ========== 6. practice/submit 端到端 ==========


class TestPracticeSubmitHTTP:
    @pytest_asyncio.fixture
    async def auth_client(self, client):
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        await client.post("/api/auth/sms-code", json={"phone": phone})
        login_resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        data = login_resp.json()["data"]
        return client, data["token"], data["user"]["id"]

    async def test_submit_aggregates_and_persists(self, auth_client):
        """choice 一题对一题错 → 聚合 10 分；mastery/streak/错题 真实落库"""
        client, token, user_id = auth_client
        uid = uuid.UUID(user_id)

        async with _test_session_factory() as s:
            kp = KnowledgePoint(code=f"TST_e2e_{uuid.uuid4().hex[:8]}", name="端到端知识点")
            s.add(kp)
            await s.flush()
            quiz = Quiz(user_id=uid, source="ai_generated", title="t", kp_codes=[kp.code])
            s.add(quiz)
            await s.flush()
            s.add(QuizItem(
                quiz_id=quiz.id, item_no=1, q_type="choice",
                question_text="1+1=?", answer="A", kp_code=kp.code,
            ))
            s.add(QuizItem(
                quiz_id=quiz.id, item_no=2, q_type="choice",
                question_text="2+2=?", answer="B", kp_code=kp.code,
            ))
            await s.commit()
            quiz_id, kp_code = quiz.id, kp.code

        resp = await client.post(
            "/api/student/practice/submit",
            json={
                "quiz_id": str(quiz_id),
                "items": [
                    {"item_no": 1, "q_type": "choice", "answer_text": "A", "hint_count": 1},
                    {"item_no": 2, "q_type": "choice", "answer_text": "C"},
                ],
                "client_submit_id": f"e2e-{uuid.uuid4().hex[:12]}",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        results = {r["item_no"]: r for r in body["data"]["results"]}
        assert results[1]["verdict"] == "correct"
        assert results[1]["score"] == 10.0
        assert results[2]["verdict"] == "wrong"
        assert results[2]["score"] == 0.0
        assert body["data"]["mastery_updated"] is True

        async with _test_session_factory() as s:
            kp_obj = (
                await s.execute(select(KnowledgePoint).where(KnowledgePoint.code == kp_code))
            ).scalar_one()
            sub = (
                await s.execute(select(Submission).where(Submission.user_id == uid))
            ).scalars().first()
            assert sub is not None
            assert sub.status == "graded"
            assert float(sub.total_score) == 10.0

            mr = await s.get(MasteryRecord, (uid, kp_obj.id))
            assert mr is not None
            assert mr.practice_count == 2
            assert mr.correct_count == 1
            assert mr.hint_count == 1

            streak = await s.get(Streak, uid)
            assert streak is not None
            assert streak.current_streak == 1
            assert streak.last_active_date == date.today()

            errors = (
                await s.execute(
                    select(ErrorRecord).where(
                        ErrorRecord.user_id == uid, ErrorRecord.kp_code == kp_code
                    )
                )
            ).scalars().all()
            assert len(errors) == 1  # 错题自动收录（含 kp_code）
            assert errors[0].question_text == "2+2=?"

    async def test_submit_idempotent_replay(self, auth_client):
        """同 client_submit_id 重放 → 不重复判分"""
        client, token, user_id = auth_client
        body = {
            # 无 quiz/assignment 归属时须携带 kp_code（迭代05 归属校验，ADR-037）
            "items": [{"item_no": 1, "q_type": "choice", "answer_text": "A", "kp_code": "MATH-G1-FUNC-001"}],
            "client_submit_id": f"e2e-{uuid.uuid4().hex[:12]}",
        }
        resp1 = await client.post(
            "/api/student/practice/submit", json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.json()["code"] == 0
        resp2 = await client.post(
            "/api/student/practice/submit", json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.json()["data"]["replayed"] is True

    async def test_submit_local_ephemeral_quiz(self, auth_client):
        """对话内 AI 出题的临时题组（local_* 非 UUID id）：不 500、按 expected_answer 判分"""
        client, token, user_id = auth_client
        resp = await client.post(
            "/api/student/practice/submit",
            json={
                "quiz_id": f"local_{uuid.uuid4().hex}",
                "items": [
                    {
                        "item_no": 1,
                        "q_type": "choice",
                        "answer_text": "C",
                        "expected_answer": "C",
                        "kp_code": "MATH-G1-FUNC-001",
                    },
                    {
                        "item_no": 2,
                        "q_type": "choice",
                        "answer_text": "A",
                        "expected_answer": "B",
                        "kp_code": "MATH-G1-FUNC-001",
                    },
                ],
                "client_submit_id": f"e2e-{uuid.uuid4().hex[:12]}",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        results = {r["item_no"]: r for r in body["data"]["results"]}
        assert results[1]["verdict"] == "correct"
        assert results[1]["score"] == 10.0
        assert results[2]["verdict"] == "wrong"
        assert results[2]["score"] == 0.0
        assert body["data"]["mastery_updated"] is True


# ========== 7. practice/start 契约（阶段 1：interaction_type 双字段兼容） ==========


class TestPracticeStartContract:
    """practice/start 返回 5 道不重复、前端可作答、含 interaction_type 的题（兼容保留 q_type）"""

    @pytest_asyncio.fixture
    async def auth_client(self, client):
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        await client.post("/api/auth/sms-code", json={"phone": phone})
        login_resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        data = login_resp.json()["data"]
        return client, data["token"], data["user"]["id"]

    async def _seed_bank(
        self, kp_code: str, *, q_types: tuple[str, ...], count: int
    ) -> None:
        """插入 count 道不同 hash 的题库题（scope=student，题库优先路径可命中）"""
        from app.models.question_bank import QuestionBank

        async with _test_session_factory() as s:
            for i in range(count):
                q_type = q_types[i % len(q_types)]
                s.add(
                    QuestionBank(
                        stem=f"TST 契约题 {kp_code} #{i} $x+{i}=0$",
                        q_type=q_type,
                        options=(
                            {"A": "A. 1", "B": "B. 2", "C": "C. 3", "D": "D. 4"}
                            if q_type == "choice"
                            else None
                        ),
                        answer="A" if q_type == "choice" else f"{i}",
                        analysis="解析",
                        difficulty="medium",
                        kp_codes=[kp_code],
                        scope="student",
                        hash=f"stg1_contract_{kp_code}_{i}",
                    )
                )
            await s.commit()

    async def test_practice_start_five_unique_renderable(self, auth_client):
        """5 道、item_no 唯一、前端可作答、interaction_type 映射正确、q_type 兼容保留"""
        client, token, user_id = auth_client
        kp_code = f"TST_ct_{uuid.uuid4().hex[:8]}"
        async with _test_session_factory() as s:
            s.add(KnowledgePoint(code=kp_code, name="契约测试知识点"))
            await s.commit()
        await self._seed_bank(kp_code, q_types=("choice", "blank", "solution"), count=5)

        resp = await client.post(
            "/api/student/practice/start",
            json={"mode": "special", "kp_code": kp_code, "count": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0, body
        items = body["data"]["items"]
        assert len(items) == 5
        assert len({x["item_no"] for x in items}) == 5  # 稳定 ID 无重复
        for item in items:
            # 双字段兼容：interaction_type 新增，q_type 保留
            assert item["interaction_type"] in {"choice", "blank", "text"}, item
            assert "q_type" in item and item["q_type"] in {"choice", "blank", "solution"}
            # 前端可作答：choice 必带 options；blank/text 不依赖 options
            if item["interaction_type"] == "choice":
                assert item.get("options"), f"choice 题必须有 options: {item}"
            # 必有题干与知识点
            assert item.get("question_text")
            assert item.get("kp_code")

    async def test_practice_start_interaction_mapping(self, auth_client):
        """映射：choice→choice、blank→blank、solution→text（count 必须 5~30，种 5 道覆盖三类型）"""
        client, token, user_id = auth_client
        kp_code = f"TST_ct_{uuid.uuid4().hex[:8]}"
        async with _test_session_factory() as s:
            s.add(KnowledgePoint(code=kp_code, name="契约映射知识点"))
            await s.commit()
        await self._seed_bank(
            kp_code,
            q_types=("choice", "blank", "choice", "blank", "solution"),
            count=5,
        )

        resp = await client.post(
            "/api/student/practice/start",
            json={"mode": "special", "kp_code": kp_code, "count": 5},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.json()["code"] == 0, resp.json()
        items = resp.json()["data"]["items"]
        assert len(items) == 5
        # 每个 item：interaction_type 必须等于 q_type 的规范映射
        for item in items:
            expected = {"choice": "choice", "blank": "blank", "solution": "text"}[item["q_type"]]
            assert item["interaction_type"] == expected, item
        # 三类型全覆盖（choice/blank/text 各至少一道，前端均可作答）
        assert {i["interaction_type"] for i in items} == {"choice", "blank", "text"}
