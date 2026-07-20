"""认证网关

JWT 解析、角色校验、依赖注入（§3.3 / §7.0）。
"""
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings


security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict:
    """解 JWT，返回用户信息（CurrentUser 依赖）

    TODO: 实现 JWT 解析逻辑
    """
    token = credentials.credentials
    # TODO: 解析 JWT，返回 {sub, active_role, roles, verified}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证未实现",
    )


def require_role(*roles: str):
    """角色检查依赖工厂

    用法：RequireRole = require_role("teacher", "admin")
    """
    async def _check(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        user_roles = current_user.get("roles", [])
        if not any(r in user_roles for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return _check
