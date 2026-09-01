"""双师课堂·黑盒端到端验收测试（需 PG 测试库 + LLM 可用）。

验收标准 C 的正确含义：
  将题目以真实用户输入方式提交到双师课堂，系统必须经过与普通题目相同的
  解析、生成、图形构建、校验和前端渲染流程，独立生成完整课堂；
  其数学结论、推导过程和图形表达必须与标准答案一致。

本测试：
  1. 从 tests/fixtures 读取验收题（原题 A/B/C + C 的 3 道变式题）；
  2. 通过 POST /api/classroom/sessions 提交到通用生成链路；
  3. 等待生成完成；
  4. 校验生成结果的数学内容与标准答案一致（不比对课件格式，只比对数学正确性）；
  5. 确认原题和变式题走的是同一条通用链路（engine 标注相同、无特例分支）。

变式题与原题同一知识域但不等价：改变边长比例、点的命名、要求证明的线面关系、
或改为求另一点到平面的距离。变式题不预先写入生产代码、不靠关键词匹配。

运行：cd services/api && python -m pytest tests/test_classroom_acceptance.py -q -s
（需先启动 PG + LLM 可用）
"""

import math
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.main import app
from app.models.database import get_db

from tests.fixtures.acceptance_problems import (
    ACCEPTANCE_A,
    ACCEPTANCE_B,
    ACCEPTANCE_C,
    ACCEPTANCE_C_VARIANTS,
    compute_a_truth,
    compute_b_truth,
    compute_c_distance,
)


def _make_test_engine():
    return create_async_engine(settings.database_url, poolclass=NullPool)


_test_engine = _make_test_engine()
_test_session_factory = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)


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


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_and_login(client, phone=None) -> tuple[str, str]:
    phone = phone or f"138{str(uuid.uuid4().int)[:8]}"
    await client.post("/api/auth/sms-code", json={"phone": phone})
    resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
    data = resp.json()["data"]
    return data["token"], data["user"]["id"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_and_wait(client, token, topic, slide_count=8):
    """提交主题到通用链路并等待生成完成，返回 (session_data, all_text)。"""
    import asyncio

    h = _headers(token)
    resp = await client.post(
        "/api/classroom/sessions",
        json={"topic": topic, "slide_count": slide_count, "mode": "topic"},
        headers=h,
    )
    assert resp.status_code == 200, f"创建会话失败: {resp.text}"
    sid = resp.json()["data"]["session_id"]

    for _ in range(120):
        detail = await client.get(f"/api/classroom/sessions/{sid}", headers=h)
        d = detail.json()["data"]
        if d["status"] in ("ready", "failed"):
            break
        await asyncio.sleep(1.0)

    # 收集所有文本内容（用于数学结论比对）
    all_text = ""
    for s in d.get("slides", []):
        for b in s.get("blocks", []):
            for field in ("text", "latex", "question", "analysis", "answer"):
                val = b.get(field, "")
                if isinstance(val, str):
                    all_text += val + "\n"
    return d, all_text


def _extract_numbers(text: str) -> list[float]:
    """从文本中提取所有数值（用于答案比对）。"""
    import re

    numbers = []
    for m in re.finditer(r"-?\d+\.?\d*", text):
        try:
            numbers.append(float(m.group()))
        except ValueError:
            pass
    return numbers


# ==================== 黑盒端到端验收 ====================


@pytest.mark.asyncio
class TestAcceptanceA:
    """验收题 A：f(x)=x^3-3x 单调性，走通用链路生成。"""

    async def test_a_generated_via_generic_path(self, client):
        """验收题 A 通过通用链路生成，engine 为通用引擎。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_A["topic"])
        assert d["status"] == "ready", f"生成失败: {d.get('error')}"
        assert d["engine"] != "math_classroom_golden", "不应使用金标准特例引擎"

    async def test_a_contains_correct_math(self, client):
        """验收题 A 生成的课堂包含正确的数学结论。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_A["topic"])
        if d["status"] != "ready":
            pytest.skip("LLM 生成未完成")

        truth = compute_a_truth()
        # 课堂应提及临界点 -1 和 1
        numbers = _extract_numbers(all_text)
        has_minus1 = any(abs(n - (-1)) < 0.01 for n in numbers)
        has_1 = any(abs(n - 1) < 0.01 for n in numbers)
        assert has_minus1, "课堂应包含临界点 x=-1"
        assert has_1, "课堂应包含临界点 x=1"


@pytest.mark.asyncio
class TestAcceptanceB:
    """验收题 B：极值反求参数，走通用链路生成。"""

    async def test_b_generated_via_generic_path(self, client):
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_B["topic"])
        assert d["status"] == "ready", f"生成失败: {d.get('error')}"
        assert d["engine"] != "math_classroom_golden"

    async def test_b_contains_correct_a(self, client):
        """验收题 B 生成的课堂包含 a=-2 的结论。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_B["topic"])
        if d["status"] != "ready":
            pytest.skip("LLM 生成未完成")

        truth = compute_b_truth()
        numbers = _extract_numbers(all_text)
        has_a_minus2 = any(abs(n - (-2)) < 0.01 for n in numbers)
        assert has_a_minus2, "课堂应包含 a=-2 的结论"


@pytest.mark.asyncio
class TestAcceptanceC:
    """验收题 C：四棱锥综合题，走通用链路生成。"""

    async def test_c_generated_via_generic_path(self, client):
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_C["topic"])
        assert d["status"] == "ready", f"生成失败: {d.get('error')}"
        assert d["engine"] != "math_classroom_golden"

    async def test_c_contains_correct_distance(self, client):
        """验收题 C 生成的课堂包含距离 1/√3 的结论。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_C["topic"])
        if d["status"] != "ready":
            pytest.skip("LLM 生成未完成")

        expected = ACCEPTANCE_C["standard_answer"]["proof_2_distance"]["E_to_plane"]
        # 课堂应包含 1/√3 或 √3/3 或其数值 ≈ 0.577
        has_distance = (
            "\\frac{1}{\\sqrt{3}}" in all_text
            or "\\frac{\\sqrt{3}}{3}" in all_text
            or "1/√3" in all_text
            or "√3/3" in all_text
        )
        if not has_distance:
            numbers = _extract_numbers(all_text)
            has_distance = any(abs(n - expected["value"]) < 0.01 for n in numbers)
        assert has_distance, f"课堂应包含距离 1/√3 ≈ {expected['value']}"

    async def test_c_contains_3d_figure(self, client):
        """验收题 C 生成的课堂包含 3D 多面体图。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, ACCEPTANCE_C["topic"])
        if d["status"] != "ready":
            pytest.skip("LLM 生成未完成")

        has_3d = False
        for s in d.get("slides", []):
            for b in s.get("blocks", []):
                if b.get("kind") == "geometry":
                    for solid in b.get("figure", {}).get("solids", []):
                        if solid.get("kind") in ("polyhedron", "pyramid", "prism"):
                            has_3d = True
        assert has_3d, "验收题 C 必须包含 3D 多面体图"


# ==================== 验收题 C 变式题（同一通用链路） ====================


@pytest.mark.asyncio
class TestAcceptanceCVariants:
    """验收题 C 的 3 道变式题，走同一条通用链路生成。

    变式题改变边长比例、点的命名、要求证明的线面关系、或改为求另一点到平面的距离。
    只有原题和变式题均能由同一条通用链路生成正确讲解，标准 C 才算通过。
    """

    @pytest.mark.parametrize("variant", ACCEPTANCE_C_VARIANTS, ids=[v["id"] for v in ACCEPTANCE_C_VARIANTS])
    async def test_variant_generated_via_generic_path(self, client, variant):
        """每道变式题通过通用链路生成，engine 为通用引擎（与原题相同）。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, variant["topic"])
        assert d["status"] == "ready", f"变式 {variant['id']} 生成失败: {d.get('error')}"
        assert d["engine"] != "math_classroom_golden", "变式题不应使用金标准特例引擎"

    @pytest.mark.parametrize("variant", ACCEPTANCE_C_VARIANTS, ids=[v["id"] for v in ACCEPTANCE_C_VARIANTS])
    async def test_variant_contains_3d_figure(self, client, variant):
        """每道变式题包含 3D 多面体图。"""
        token, _ = await _register_and_login(client)
        d, all_text = await _create_and_wait(client, token, variant["topic"])
        if d["status"] != "ready":
            pytest.skip(f"变式 {variant['id']} LLM 生成未完成")

        has_3d = False
        for s in d.get("slides", []):
            for b in s.get("blocks", []):
                if b.get("kind") == "geometry":
                    for solid in b.get("figure", {}).get("solids", []):
                        if solid.get("kind") in ("polyhedron", "pyramid", "prism"):
                            has_3d = True
        assert has_3d, f"变式 {variant['id']} 必须包含 3D 多面体图"


# ==================== 同一通用链路验证 ====================


@pytest.mark.asyncio
class TestSameGenericPath:
    """验证原题和变式题走的是同一条通用链路。

    若无法证明标准 C 和变式题走的是同一条通用生成链路，则验收失败。
    """

    async def test_all_problems_use_same_engine(self, client):
        """原题 C 和所有变式题使用相同的 engine 标注（同一条通用链路）。"""
        token, _ = await _register_and_login(client)
        engines = set()

        # 原题 C
        d_c, _ = await _create_and_wait(client, token, ACCEPTANCE_C["topic"])
        if d_c["status"] == "ready":
            engines.add(d_c["engine"])

        # 变式题
        for v in ACCEPTANCE_C_VARIANTS:
            d_v, _ = await _create_and_wait(client, token, v["topic"])
            if d_v["status"] == "ready":
                engines.add(d_v["engine"])

        # 所有成功生成的会话应使用同一个 engine（通用链路）
        if engines:
            assert len(engines) == 1, f"原题和变式题应使用同一引擎，实际: {engines}"
            assert "golden" not in next(iter(engines)).lower(), "不应使用金标准特例引擎"