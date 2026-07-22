"""认证网关

JWT 解析、角色校验、依赖注入（§3.3 / §7.0）。
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.gateway.jwt import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> dict:
    """解 JWT，返回用户信息（CurrentUser 依赖）

    Returns:
        dict: {sub, active_role, roles, verified}

    Raises:
        HTTPException: 401 未认证/token 过期/非法
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_token(token)
        user_id: str | None = payload.get("sub")
        active_role: str = payload.get("active_role", "student")
        roles: list = payload.get("roles", [])
        verified: bool = payload.get("verified", False)

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 将 user_id 转为 UUID 格式验证
        try:
            uuid.UUID(user_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的 token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

        return {
            "sub": user_id,
            "active_role": active_role,
            "roles": roles,
            "verified": verified,
        }

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token 已过期或无效",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


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


def require_class_scope():
    """班级数据范围检查依赖工厂（§5.5 三层注入之二）

    用法：RequireClassScope = require_class_scope()
    注意：路由必须声明 {class_id} path 参数，class_id 由 FastAPI 自动注入
    """

    async def _check(
        class_id: str,
        current_user: Annotated[dict, Depends(get_current_user)],
    ) -> dict:
        # M0 兼容占位：从 current_user 读 class_ids 属性
        # TODO: M1 班级域落地时接真实校验（ClassTeacher / ClassStudent 关联表）
        class_ids = current_user.get("class_ids", [])
        if class_id not in class_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问该班级数据",
            )
        return current_user

    return _check


def require_verified():
    """实名认证检查依赖工厂（§5.5 三层注入之三）

    用法：RequireVerified = require_verified()
    """

    async def _check(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        # M0 兼容占位：从 current_user 读 verified / is_verified 属性
        # TODO: M1 接入真实实名认证状态
        verified = current_user.get("verified") or current_user.get("is_verified")
        if not verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账号未完成认证",
            )
        return current_user

    return _check
