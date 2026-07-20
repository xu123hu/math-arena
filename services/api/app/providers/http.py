"""统一 HTTP 客户端（providers/http.py）

全局单例，连接池复用（性能红线手段）。
"""

import httpx

_client: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    """获取全局 httpx 客户端（单例）"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=5.0),
            limits=httpx.Limits(max_connections=50),
        )
    return _client


async def close_http() -> None:
    """关闭全局客户端"""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
