"""Redis 工具模块

提供 Redis 连接管理和常用操作。
"""

import redis.asyncio as redis

from app.config import settings

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """获取 Redis 客户端单例"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True, protocol=2)
    return _redis_client


async def close_redis() -> None:
    """关闭 Redis 连接"""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


# ========== 验证码相关 ==========

SMS_CODE_PREFIX = "sms:"
SMS_RATE_PREFIX = "sms_rate:"
SMS_CODE_TTL = 300  # 验证码有效期 5 分钟
SMS_RATE_TTL = 60  # 发送间隔 60 秒


async def set_sms_code(phone: str, code: str) -> None:
    """存储短信验证码"""
    r = get_redis()
    await r.set(f"{SMS_CODE_PREFIX}{phone}", code, ex=SMS_CODE_TTL)


async def get_sms_code(phone: str) -> str | None:
    """获取短信验证码"""
    r = get_redis()
    return await r.get(f"{SMS_CODE_PREFIX}{phone}")


async def delete_sms_code(phone: str) -> None:
    """删除短信验证码（验证通过后）"""
    r = get_redis()
    await r.delete(f"{SMS_CODE_PREFIX}{phone}")


async def check_sms_rate_limit(phone: str) -> bool:
    """检查发送频率限制

    Returns:
        True 表示可以发送，False 表示频率过快
    """
    r = get_redis()
    key = f"{SMS_RATE_PREFIX}{phone}"
    exists = await r.exists(key)
    if exists:
        return False
    await r.set(key, "1", ex=SMS_RATE_TTL)
    return True
