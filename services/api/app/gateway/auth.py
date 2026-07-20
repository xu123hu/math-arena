"""认证网关

JWT 解析、角色校验、依赖注入（§3.3 / §7.0）。
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> dict:
    """解 JWT，返回用户信息（CurrentUser 依赖）

    TODO: 实现 JWT 解析逻辑
    """
    _token = credentials.credentials  # noqa: F841  # TODO: 实现 JWT 解析
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
