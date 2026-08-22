"""Test公共配置和 fixtures

【隔离架构（迭代09+ 根治）】
- 测试强制使用独立测试库 test_math_arena（与开发库 math_arena 完全隔离），
  DATABASE_URL 环境变量必须在任何 app 模块 import 之前设置——
  因为 app/models/database.py 在 import 时即用 settings.database_url 创建 engine。
- pytest_sessionstart：确保 test_math_arena 库存在（含 pgvector 扩展）+ 全量建表（干净起点）。
- 每个测试后 _cleanup_pb_test_data 清理测试命名空间数据（防 test 库膨胀）。
- 开发库（math_arena）从此零污染：真实知识库/题库数据不会被测试 fixture 触碰。

用法：
    cd services/api
    python -m pytest tests/ -q
"""

import os

# ⚠️ 必须最先执行（任何 app.* import 之前）：覆盖为独立测试库
os.environ["DATABASE_URL"] = "postgresql+asyncpg://postgres:postgres@localhost:54329/test_math_arena"
# M3 教师端在测试 profile 显式开启（默认生产关闭，见 app/config.py m3_enable_teacher）。
# 默认关闭的契约由子进程测试证明（tests/test_m3_teacher_profile.py）。
os.environ["M3_ENABLE_TEACHER"] = "true"

import contextlib

import pytest

from app.providers.http import close_http
from app.skills.registry import register_builtin_skills

# ASGITransport 不执行 lifespan，内置 skills 需在测试会话中显式注册
register_builtin_skills()


_TEST_DATABASE = "test_math_arena"


async def _require_test_database(connection) -> None:
    """拒绝在非专用测试库上执行破坏性 schema 操作。"""
    database_name = await connection.fetchval("SELECT current_database()")
    if database_name != _TEST_DATABASE:
        raise RuntimeError(
            f"refusing destructive test schema reset outside {_TEST_DATABASE}: {database_name!r}"
        )


def _ensure_test_db() -> None:
    """确保专用测试数据库存在（幂等）。"""
    import asyncio

    import asyncpg

    async def _run():
        admin = await asyncpg.connect(host="localhost", port=54329, user="postgres", password="postgres", database="postgres")
        try:
            exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", _TEST_DATABASE)
            if not exists:
                await admin.execute(f"CREATE DATABASE {_TEST_DATABASE}")
                print(f"[conftest] 已创建测试库 {_TEST_DATABASE}")
        finally:
            await admin.close()

    asyncio.run(_run())


def _reset_test_schema() -> None:
    """重建专用测试库的 public schema，兼容 SQLAlchemy 未映射的遗留表。"""
    import asyncio

    import asyncpg

    async def _run():
        target = await asyncpg.connect(
            host="localhost",
            port=54329,
            user="postgres",
            password="postgres",
            database=_TEST_DATABASE,
        )
        try:
            await _require_test_database(target)
            await target.execute("DROP SCHEMA public CASCADE")
            await target.execute("CREATE SCHEMA public AUTHORIZATION postgres")
            await target.execute("GRANT ALL ON SCHEMA public TO postgres")
            await target.execute("GRANT ALL ON SCHEMA public TO public")
            # pgvector 向量类型 + pg_trgm（RAG trgm 召回路依赖 word_similarity 函数）
            await target.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await target.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        finally:
            await target.close()

    asyncio.run(_run())


def _seed_kp_whitelist() -> None:
    """从开发库复制 52 个真实 MATH 知识点到测试库（kp 白名单种子）

    KB import 校验 kp_codes ⊆ knowledge_points；RAG/图谱测试依赖真实 kp 树。
    仅复制 knowledge_points 小表（几 KB），不复制 chunks/question_bank（测试自建）。
    """
    import asyncio

    import asyncpg

    async def _run():
        dev = await asyncpg.connect(host="localhost", port=54329, user="postgres", password="postgres", database="math_arena")
        tgt = await asyncpg.connect(host="localhost", port=54329, user="postgres", password="postgres", database="test_math_arena")
        try:
            rows = await dev.fetch(
                "SELECT id, parent_id, grade, code, name, aliases FROM knowledge_points WHERE code LIKE 'MATH-%'"
            )
            for r in rows:
                await tgt.execute(
                    "INSERT INTO knowledge_points (id, parent_id, grade, code, name, aliases, created_at, updated_at) "
                    "VALUES ($1,$2,$3,$4,$5,$6, now(), now()) ON CONFLICT (code) DO NOTHING",
                    r["id"], r["parent_id"], r["grade"], r["code"], r["name"], r["aliases"],
                )
            print(f"[conftest] 已复制 {len(rows)} 个真实知识点到测试库")
        finally:
            await dev.close()
            await tgt.close()

    asyncio.run(_run())


def pytest_sessionstart(session) -> None:  # noqa: ARG001
    """会话开始：确保测试库存在 + 建表 + 种子（幂等）"""
    _ensure_test_db()
    _reset_test_schema()
    import asyncio

    from sqlalchemy import text

    from app.models import Base
    from app.models.database import engine

    async def _init():
        async with engine.begin() as conn:
            database_name = await conn.scalar(text("SELECT current_database()"))
            if database_name != _TEST_DATABASE:
                raise RuntimeError(
                    f"refusing test schema initialization outside {_TEST_DATABASE}: {database_name!r}"
                )
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init())
    print("[conftest] 测试库表结构已重建（干净起点）")
    _seed_kp_whitelist()


@pytest.fixture(autouse=True)
async def _reset_singletons():
    """每个测试前后重置全局单例，避免连接池跨循环冲突"""
    import app.gateway.redis as redis_mod

    # 测试前：重置 Redis 连接
    if redis_mod._redis_client is not None:
        with contextlib.suppress(Exception):
            await redis_mod.close_redis()
        redis_mod._redis_client = None

    # 测试前：关闭跨循环的 httpx 客户端（下次使用时按当前循环重建）
    with contextlib.suppress(Exception):
        await close_http()
    # 测试前：清空应用 DB 连接池——池内连接绑定的是上一个（已关闭的）测试循环，
    # 复用会抛 "Task got Future attached to a different loop"，后台任务静默写库失败
    with contextlib.suppress(Exception):
        from app.models.database import engine as _app_engine

        await _app_engine.dispose()

    yield

    # 测试后：清理 Redis + httpx
    with contextlib.suppress(Exception):
        await redis_mod.close_redis()
    with contextlib.suppress(Exception):
        await close_http()
    with contextlib.suppress(Exception):
        from app.models.database import engine as _app_engine

        await _app_engine.dispose()


@pytest.fixture(autouse=True)
async def _cleanup_pb_test_data():
    """迭代09 治理：测试直接用开发库（settings.database_url），大量用例以
    "pb{uuid}" 前缀造测试知识点（空点/校验点/题库点等），结束后若不清理会污染
    真实数据（错题本/图谱/组卷全被脏点污染，见迭代09 突破文档 §13）。
    本 fixture 在每个测试结束后删除测试命名空间数据（含关联表），保持开发库干净。

    测试命名空间（与真实前缀识别规则配套，见 mock_exam._REAL_KP_PREFIXES）：
    - pb{hex}：空点/校验点/题库点（历史污染，白名单外，生产代码直接过滤）
    - BK{6hex}-NNN：topic 组卷测试（BK 后直接跟 6 位 hex 为测试命名空间）
    - MX{4hex}-M{n}-NNN：full_mock 混合模块测试
    - TST 前缀：各测试文件自清洁命名空间（此处兜底清理，防跨文件漏清）
    真实 BK/MX 知识点为 "BK-XXX" / "MX-XXX"（带连字符）形态，不受影响。

    依赖表删除顺序：先子表后父表；清理失败不掩盖测试结果（suppress）。
    """
    yield
    try:
        from sqlalchemy import delete, text

        from app.models.database import async_session_factory
        from app.models.knowledge_point import KnowledgePoint

        # 测试知识点识别正则：pb{hex} / BK{6hex}-NNN / MX{4hex}-M{n}-NNN / TST 前缀
        test_kp_cond = (
            "code LIKE 'pb%' "
            "OR code LIKE 'TST%' "
            "OR code ~ '^BK[0-9a-f]{6}-[0-9]{3}$' "
            "OR code ~ '^MX[0-9a-f]{4}-M[0-9]-[0-9]{3}$' "
            "OR code ~ '^BK[0-9a-f]{6}$' "
            "OR code ~ '^MX[0-9a-f]{4}-M[0-9]$'"
        )

        async with async_session_factory() as session:
            # 子表先删（外键依赖）：kp_code 直连 或 kp_id 关联测试知识点
            # e2e_ 前缀为 test_student_linkage 联调错题（无 KP 行，也一并清理）
            for table in (
                "quiz_items",
                "error_records",
                "mastery_records",
                "mastery_snapshots",
                "daily_questions",
            ):
                with contextlib.suppress(Exception):
                    await session.execute(
                        text(
                            f"DELETE FROM {table} WHERE (kp_code LIKE 'pb%') "
                            f"OR (kp_code LIKE 'TST%') "
                            f"OR (kp_code LIKE 'e2e_%') "
                            f"OR (kp_code ~ '^BK[0-9a-f]{{6}}-[0-9]{{3}}$') "
                            f"OR (kp_code ~ '^MX[0-9a-f]{{4}}-M[0-9]-[0-9]{{3}}$') "
                            f"OR (kp_id IN (SELECT id FROM knowledge_points WHERE {test_kp_cond}))"
                        )
                    )
            # 测试知识点本身
            await session.execute(
                delete(KnowledgePoint).where(
                    (KnowledgePoint.code.like("pb%"))
                    | (KnowledgePoint.code.like("TST%"))
                    | (KnowledgePoint.code.regexp_match(r"^BK[0-9a-f]{6}-[0-9]{3}$"))
                    | (KnowledgePoint.code.regexp_match(r"^MX[0-9a-f]{4}-M[0-9]-[0-9]{3}$"))
                    | (KnowledgePoint.code.regexp_match(r"^BK[0-9a-f]{6}$"))
                    | (KnowledgePoint.code.regexp_match(r"^MX[0-9a-f]{4}-M[0-9]$"))
                )
            )
            await session.commit()
    except Exception:
        pass
