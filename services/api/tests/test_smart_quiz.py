"""smart_quiz 三闸验证测试（迭代02；M2 重构后更新）

覆盖：
1. 三闸各闸独立语义：字段/self_check 硬软项/公式配对/本地 sympify 格式检查
   （M2 重构：删除"LLM 现场编写 sympy_check_code 并沙箱执行"机检闸——误判率高于
   拦截率且制造 20~40s 额外延迟，SymPy 降级为纯本地格式检查工具，不再做真假裁判）
2. run() 全流程：闸失败 → 带反馈重生成 → 通过出题；两次均失败 → 诚实降级不出错题
3. _parse_request：KP_MAP 未命中 → LLM 小 JSON 抽取知识点

纯 mock（ctx.rag=None 跳过题库检索），无需数据库。
"""

import json
from unittest.mock import MagicMock

from app.skills.base import SkillContext
from app.skills.smart_quiz.main import (
    SmartQuizExecutor,
    _is_clone_variant,
    _parse_count,
    parse_quiz_json,
)


def _ctx(llm) -> SkillContext:
    return SkillContext(
        user_id="u1",
        user_role="student",
        conversation_id="c1",
        request_id="r1",
        db=MagicMock(),
        llm=llm,
        rag=None,
    )


class MockLLM:
    intended_provider = "mock"

    def __init__(self, responses: list[str]):
        self.queue = list(responses)
        self.calls: list[dict] = []

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        content = self.queue.pop(0) if self.queue else "{}"
        return {"content": content}


QUIZ_OK = json.dumps(
    {
        "q_type": "choice",
        "question_text": "求 $f(x)=x^2$ 在 $x=1$ 处的导数",
        "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
        "answer": "B",
        "answer_analysis": "[[STEP]]\n由幂函数求导公式得 $f'(x)=2x$",
        "self_check": {
            "answer_verified": True,
            "computation_double_checked": True,
            "no_ambiguity": True,
            "difficulty_match": True,
            "in_syllabus": True,
            "note": "已代回验证",
        },
    },
    ensure_ascii=False,
)

QUIZ_NO_ANSWER = json.dumps(
    {"q_type": "choice", "question_text": "1+1=?", "options": ["A. 1", "B. 2", "C. 3", "D. 4"]},
    ensure_ascii=False,
)

QUIZ_SELF_CHECK_FAIL = json.dumps(
    {
        "q_type": "choice",
        "question_text": "求 $f(x)=x^2$ 的导数",
        "options": ["A. x", "B. 2x", "C. 3x", "D. 4x"],
        "answer": "A",
        "self_check": {"answer_verified": False, "note": "没验证"},
    },
    ensure_ascii=False,
)

QUIZ_BAD_FORMULA = json.dumps(
    {
        "q_type": "blank",
        "question_text": "求 $f(x)=x^2 的零点",  # $ 不配对
        "options": [],
        "answer": "0",
    },
    ensure_ascii=False,
)


async def _run(executor: SmartQuizExecutor, params: dict, ctx: SkillContext) -> list[dict]:
    return [ev async for ev in executor.run(params, ctx)]


def _cards(events: list[dict]) -> list[dict]:
    return [e["data"] for e in events if e.get("type") == "card"]


def _text(events: list[dict]) -> str:
    return "".join(e["data"].get("text", "") for e in events if e.get("type") == "token")


# ========== 1. 三闸独立语义 ==========


class TestThreeGates:
    async def test_missing_answer_fails(self):
        ex = SmartQuizExecutor()
        quiz = parse_quiz_json(QUIZ_NO_ANSWER)
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("答案" in f for f in failures)

    async def test_choice_needs_four_options(self):
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "choice",
            "question_text": "1+1=?",
            "options": ["A. 1", "B. 2"],
            "answer": "B",
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("选项" in f for f in failures)

    async def test_self_check_hard_key_false_fails(self):
        ex = SmartQuizExecutor()
        quiz = parse_quiz_json(QUIZ_SELF_CHECK_FAIL)
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("answer_verified" in f for f in failures)

    async def test_self_check_absent_skips_with_note(self):
        ex = SmartQuizExecutor()
        quiz = {"q_type": "blank", "question_text": "1+1=?", "options": [], "answer": "2"}
        passed, failures, notes = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert passed and not failures
        assert any("self_check" in n for n in notes)

    async def test_unpaired_formula_fails(self):
        ex = SmartQuizExecutor()
        quiz = parse_quiz_json(QUIZ_BAD_FORMULA)
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("公式" in f for f in failures)

    async def test_self_check_hard_key_false_fails_without_machine_gate(self):
        """M2 重构：删除机检闸后，self_check 硬键 false 仍判失败（无沙箱覆盖逻辑）"""
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "solution",
            "question_text": "求 $f(x)=x^3-3x$ 的极值",
            "options": [],
            "answer": "极大值 2，极小值 -2",
            "answer_analysis": "[[STEP]]\n求导得 $f'(x)=3x^2-3$",
            "self_check": {
                "answer_verified": False,
                "computation_double_checked": False,
                "no_ambiguity": True,
                "note": "难题没把握",
            },
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("answer_verified" in f for f in failures)

    async def test_blank_answer_format_checked_locally(self):
        """填空答案本地 sympify 格式检查：可解析的多值答案通过"""
        ex = SmartQuizExecutor()
        ok = {"q_type": "blank", "question_text": "求值", "options": [], "answer": "2 或 -2"}
        passed, failures, _ = await ex._three_gates(ok, _ctx(MockLLM([])))
        assert passed and not failures


# ========== 1.5 v1.9 解析干净化 / 答案一致性 / 变式雷同闸 ==========


class TestV19Gates:
    async def test_meta_language_in_analysis_fails(self):
        """命题草稿语言（原题参考答案/重新审视/经核算/为符合…）写进解析 → 判失败重出"""
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "choice",
            "question_text": "已知 $f(x)=\\cos x$，下列正确的是",
            "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
            "answer": "C",
            "answer_analysis": "[[STEP]] 分析。重新审视：原题参考答案为 (2)(3)，经核算正确选项应为 D。",
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("命题过程性语言" in f for f in failures)

    async def test_analysis_conclusion_mismatch_fails(self):
        """选择题解析最终结论（故选/正确选项为 X）与 answer 字母不一致 → 判失败"""
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "choice",
            "question_text": "已知 $f(x)=\\cos x$，下列正确的是",
            "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
            "answer": "C",
            "answer_analysis": "[[STEP]] 推导…… [[STEP]] 故正确选项为 D。",
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert not passed
        assert any("不一致" in f for f in failures)

    async def test_clean_analysis_with_matching_conclusion_passes(self):
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "choice",
            "question_text": "已知 $f(x)=\\cos x$，下列正确的是",
            "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
            "answer": "C",
            "answer_analysis": "[[STEP]] 取倒数得等差数列。[[STEP]] 故选 C。",
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert passed and not failures

    async def test_legit_mingti_language_not_blocked(self):
        """「命题(1)正确」是合法数学语言，不得误伤（meta 闸不含裸"命题"）"""
        ex = SmartQuizExecutor()
        quiz = {
            "q_type": "choice",
            "question_text": "四个命题中真命题是",
            "options": ["A. (1)(3)", "B. (2)(3)", "C. (1)(4)", "D. (2)(4)"],
            "answer": "A",
            "answer_analysis": "[[STEP]] 对于命题(1)，f(-x)=f(x)，命题(1)正确。[[STEP]] 综上，故选 A。",
        }
        passed, failures, _ = await ex._three_gates(quiz, _ctx(MockLLM([])))
        assert passed and not failures

    def test_clone_variant_flagged_on_same_core_formula(self):
        """实锤样例：f(x)=cosx+1/cosx 换定义域再出 → 核心公式交集命中，判雷同"""
        prev = ["已知函数 $f(x)=\\cos x+\\frac{1}{\\cos x}$，其中 $x\\in(0,\\frac{\\pi}{2})$。关于 $f(x)$ 的性质，下列结论正确的是："]
        new = "已知函数 $f(x)=\\cos x+\\frac{1}{\\cos x}$，定义域为 $\\{x|x\\neq k\\pi+\\frac{\\pi}{2},k\\in Z\\}$，则下列命题中正确的是"
        assert _is_clone_variant(new, prev)

    def test_numeric_variant_not_flagged(self):
        """换数字/换参数是合法变式（数字保留参与归一化），不得误伤"""
        prev = ["已知 $a_1=1, a_{n+1}=2a_n+1$，求 $a_n$ 的通项公式。"]
        new = "已知 $a_1=2, a_{n+1}=3a_n-2$，求 $a_n$ 的通项公式。"
        assert not _is_clone_variant(new, prev)


# ========== 2. run() 全流程 ==========


class TestRunFlow:
    async def test_gate_fail_then_regenerate_pass(self):
        """首次自检失败 → 带反馈重生成（低温）→ 通过 → 发卡，feedback 含失败原因"""
        llm = MockLLM([QUIZ_SELF_CHECK_FAIL, QUIZ_OK])
        events = await _run(SmartQuizExecutor(), {"message": "出一道导数题"}, _ctx(llm))

        cards = _cards(events)
        assert len(cards) == 1 and cards[0]["type"] == "quiz_set"
        item = cards[0]["items"][0]
        assert item["verified"] is True
        assert item["self_check"]["answer_verified"] is True
        assert item["source"] == "ai"

        assert len(llm.calls) == 2
        assert "answer_verified" in llm.calls[1]["messages"][0]["content"]  # 反馈带失败原因
        assert llm.calls[1]["temperature"] == 0.5  # 重生成降温
        stages = [e["data"]["stage"] for e in events if e.get("type") == "status"]
        assert "regenerating" in stages

    async def test_both_attempts_fail_honest_degrade(self):
        """两次生成均不过闸 → 诚实降级：不发题卡、明说原因"""
        llm = MockLLM([QUIZ_NO_ANSWER, QUIZ_NO_ANSWER])
        events = await _run(SmartQuizExecutor(), {"message": "出一道导数题"}, _ctx(llm))

        assert _cards(events) == []
        text = _text(events)
        assert "没能通过质量检查" in text
        metas = [e["data"] for e in events if e.get("type") == "_result_meta"]
        assert metas[0]["degraded"] is True

    async def test_json_parse_fail_retries(self):
        """首次输出非法 JSON → 重生成 → 通过"""
        llm = MockLLM(["这不是 JSON", QUIZ_OK])
        events = await _run(SmartQuizExecutor(), {"message": "出一道三角函数题"}, _ctx(llm))
        assert len(_cards(events)) == 1
        assert len(llm.calls) == 2


# ========== 3. 参数解析 ==========


class TestParseRequest:
    async def test_kp_map_hit(self):
        ex = SmartQuizExecutor()
        code, name, diff, qt, _theme = await ex._parse_request(
            "给我一道难一点的导数填空题", _ctx(MockLLM([]))
        )
        assert (code, name, diff, qt) == ("derivative", "导数", "hard", "blank")

    async def test_kp_map_miss_llm_extract(self):
        """KP_MAP 未命中（复数）→ LLM 抽取 → kp_code=custom"""
        llm = MockLLM(['{"kp_name": "复数"}'])
        ex = SmartQuizExecutor()
        code, name, diff, qt, _theme = await ex._parse_request("出一道复数的基础题", _ctx(llm))
        assert (code, name, diff, qt) == ("custom", "复数", "easy", "choice")

    async def test_kp_extract_failure_falls_back(self):
        llm = MockLLM(["非 JSON 输出"])
        ex = SmartQuizExecutor()
        code, name, _, _, _ = await ex._parse_request("随便出一道题", _ctx(llm))
        assert (code, name) == ("function", "函数")


# ========== 4. 多题生成（几道 → 封顶 3 道） ==========


class TestParseCount:
    def test_default_one(self):
        assert _parse_count("出一道三角函数题") == 1

    def test_jidao_three(self):
        assert _parse_count("帮我出几道三角函数的压轴题") == 3

    def test_liangdao_two(self):
        assert _parse_count("出两道导数题") == 2

    def test_digit_capped(self):
        assert _parse_count("出 5 道函数题") == 3


class TestMultiItem:
    async def test_multi_items_all_pass(self):
        """几道 → 逐题过闸 → 一张卡多题，编号齐全"""
        llm = MockLLM([QUIZ_OK, QUIZ_OK, QUIZ_OK])
        events = await _run(SmartQuizExecutor(), {"message": "出几道函数题"}, _ctx(llm))
        cards = _cards(events)
        assert len(cards) == 1 and len(cards[0]["items"]) == 3
        assert [it["item_no"] for it in cards[0]["items"]] == [1, 2, 3]
        text = _text(events)
        # v1.9：token 只发引导语（题干/答案全在卡片内，不再文本 dump 重复+外漏答案）
        assert "共 3 道" in text and "点选项作答" in text
        assert "第 2 题" not in text and "答案" not in text

    async def test_multi_items_partial_with_note(self):
        """一题两稿全败 → 略去并明示，其余照出（绝不出错题）"""
        llm = MockLLM([QUIZ_OK, QUIZ_NO_ANSWER, QUIZ_NO_ANSWER, QUIZ_OK])
        events = await _run(SmartQuizExecutor(), {"message": "出几道函数题"}, _ctx(llm))
        cards = _cards(events)
        assert len(cards) == 1 and len(cards[0]["items"]) == 2
        assert "另有 1 道未通过质量检查" in _text(events)

    async def test_multi_item_llm_error_isolated(self):
        """单题 LLM 瞬时异常不拖垮整批：跳过该题，其余照出"""

        class FlakyLLM(MockLLM):
            async def chat(self, messages, **kwargs):
                if len(self.calls) == 1:  # 第 2 题首次调用抛异常
                    self.calls.append({"messages": messages, **kwargs})
                    raise ConnectionError("provider down")
                return await super().chat(messages, **kwargs)

        llm = FlakyLLM([QUIZ_OK, QUIZ_OK])
        events = await _run(SmartQuizExecutor(), {"message": "出两道函数题"}, _ctx(llm))
        cards = _cards(events)
        assert len(cards) == 1 and len(cards[0]["items"]) == 1
        assert "另有 1 道" in _text(events)
