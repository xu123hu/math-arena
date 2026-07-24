"""Test公共配置和 fixtures"""

import contextlib

import pytest

from app.providers.http import close_http
from app.skills.registry import register_builtin_skills

# ASGITransport 不执行 lifespan，内置 skills 需在测试会话中显式注册
register_builtin_skills()


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

    yield

    # 测试后：清理 Redis + httpx
    with contextlib.suppress(Exception):
        await redis_mod.close_redis()
    with contextlib.suppress(Exception):
        await close_http()
