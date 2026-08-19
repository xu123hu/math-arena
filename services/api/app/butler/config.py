"""Butler 授权配置解析（阶段 5a：配置即用后端控制面）

三层回退：env（兜底层）→ system_configs["butler.authorization"]（全局默认覆盖）。
- external_allowed        外部工具（EXTERNAL 风险）授权开关，默认 false
- web_search_enabled      联网搜索总开关，默认回退 env settings.web_search_enabled
- web_search_local_refused 本地检索拒答标记（本地无答案时允许联网兜底），默认 false
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.system_config import get_system_config

BUTLER_AUTHORIZATION_KEY = "butler.authorization"
BUTLER_AUTHORIZATION_FIELDS = (
    "external_allowed",
    "web_search_enabled",
    "web_search_local_refused",
)


async def resolve_butler_authorization(db: AsyncSession) -> dict[str, bool]:
    """读取 Butler 授权开关有效值（env ← system_configs["butler.authorization"]）。"""
    stored = await get_system_config(db, BUTLER_AUTHORIZATION_KEY, default={})
    if not isinstance(stored, dict):
        stored = {}
    return {
        "external_allowed": bool(stored.get("external_allowed", False)),
        "web_search_enabled": bool(
            stored.get("web_search_enabled", settings.web_search_enabled)
        ),
        "web_search_local_refused": bool(stored.get("web_search_local_refused", False)),
    }
