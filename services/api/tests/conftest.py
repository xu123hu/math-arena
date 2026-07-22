"""Test公共配置和 fixtures"""

import contextlib

import pytest


@pytest.fixture(autouse=True)
async def _reset_singletons():
    """每个测试前后重置全局单例，避免连接池跨循环冲突"""
    import app.gateway.redis as redis_mod

    # 测试前：重置 Redis 连接
    if redis_mod._redis_client is not None:
        with contextlib.suppress(Exception):
            await redis_mod.close_redis()
        redis_mod._redis_client = None

    yield

    # 测试后：清理 Redis
    with contextlib.suppress(Exception):
        await redis_mod.close_redis()
