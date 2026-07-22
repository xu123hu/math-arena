"""认证路由

实现 /api/auth/* 系列端点（API 文档 §2）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gateway import redis as redis_util
from app.gateway.auth import get_current_user
from app.gateway.jwt import create_token_with_role
from app.gateway.schemas import (
    ApiResponse,
    LoginData,
    LoginRequest,
    MeData,
    RoleInfo,
    RoleSwitchData,
    RoleSwitchRequest,
    SmsCodeData,
    SmsCodeRequest,
    UserData,
)
from app.models.database import get_db
from app.models.role_binding import RoleBinding
from app.models.user import User

router = APIRouter()


# ========== POST /sms-code ==========


@router.post("/sms-code", response_model=ApiResponse)
async def send_sms_code(body: SmsCodeRequest):
    """发送短信验证码（开发环境固定 123456）"""
    # 检查发送频率限制
    can_send = await redis_util.check_sms_rate_limit(body.phone)
    if not can_send:
        return ApiResponse(code=42901, message="发送频率过快，请 60 秒后重试")

    # 开发环境使用固定验证码
    code = settings.dev_sms_code
    await redis_util.set_sms_code(body.phone, code)

    return ApiResponse(code=0, message="sent", data=SmsCodeData(ttl=redis_util.SMS_CODE_TTL))


# ========== POST /login ==========


@router.post("/login", response_model=ApiResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """验证码登录（新用户自动注册）"""
    # 验证验证码
    stored_code = await redis_util.get_sms_code(body.phone)
    if stored_code is None:
        return ApiResponse(code=40002, message="验证码已过期，请重新获取")
    if stored_code != body.code:
        return ApiResponse(code=40002, message="验证码错误")

    # 验证码正确，删除已用验证码
    await redis_util.delete_sms_code(body.phone)

    # 查找或创建用户
    result = await db.execute(
        select(User).where(User.phone == body.phone, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    is_new = False
    if user is None:
        # 新用户自动注册
        is_new = True
        user = User(phone=body.phone, nickname="")
        db.add(user)
        await db.flush()  # 获取 user.id

        # 创建默认角色绑定 student
        role_binding = RoleBinding(user_id=user.id, role="student", verified=False)
        db.add(role_binding)
        await db.flush()

    # 查询用户所有角色
    roles_result = await db.execute(
        select(RoleBinding).where(RoleBinding.user_id == user.id, RoleBinding.deleted_at.is_(None))
    )
    role_bindings = roles_result.scalars().all()
    roles_list = [
        RoleInfo(role=rb.role, verified=rb.verified, org_name=rb.org_name) for rb in role_bindings
    ]
    role_names = [rb.role for rb in role_bindings]

    # 默认激活第一个角色
    active_role = role_names[0] if role_names else "student"
    # 找到激活角色的 verified 状态
    active_rb = next((rb for rb in role_bindings if rb.role == active_role), None)
    verified = active_rb.verified if active_rb else False

    # 签发 JWT
    token = create_token_with_role(
        user_id=str(user.id),
        role=active_role,
        roles=role_names,
        verified=verified,
    )

    user_data = UserData(
        id=str(user.id),
        nickname=user.nickname or "",
        active_role=active_role,
        roles=roles_list,
        is_new=is_new,
    )

    return ApiResponse(code=0, message="ok", data=LoginData(token=token, user=user_data))


# ========== GET /me ==========


@router.get("/me", response_model=ApiResponse)
async def get_me(
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """获取当前用户信息"""
    user_id = current_user["sub"]

    # 查询用户
    result = await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        return ApiResponse(code=40401, message="用户不存在")

    # 查询角色绑定
    roles_result = await db.execute(
        select(RoleBinding).where(RoleBinding.user_id == user.id, RoleBinding.deleted_at.is_(None))
    )
    role_bindings = roles_result.scalars().all()
    roles_list = [
        RoleInfo(role=rb.role, verified=rb.verified, org_name=rb.org_name) for rb in role_bindings
    ]

    active_role = current_user.get("active_role", "student")

    return ApiResponse(
        code=0,
        message="ok",
        data=MeData(
            id=str(user.id),
            nickname=user.nickname or "",
            avatar_url=user.avatar_url,
            active_role=active_role,
            roles=roles_list,
        ),
    )


# ========== POST /role/switch ==========


@router.post("/role/switch", response_model=ApiResponse)
async def switch_role(
    body: RoleSwitchRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """切换角色（换发 JWT）"""
    user_id = current_user["sub"]
    target_role = body.role

    # 查询用户在该角色上的绑定
    result = await db.execute(
        select(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role == target_role,
            RoleBinding.deleted_at.is_(None),
        )
    )
    role_binding = result.scalar_one_or_none()

    if role_binding is None:
        return ApiResponse(code=40301, message=f"未绑定 {target_role} 角色")

    # 查询用户所有角色
    roles_result = await db.execute(
        select(RoleBinding).where(RoleBinding.user_id == user_id, RoleBinding.deleted_at.is_(None))
    )
    role_bindings = roles_result.scalars().all()
    role_names = [rb.role for rb in role_bindings]

    # 换发包含新角色的 JWT
    token = create_token_with_role(
        user_id=str(user_id),
        role=target_role,
        roles=role_names,
        verified=role_binding.verified,
    )

    return ApiResponse(code=0, message="ok", data=RoleSwitchData(token=token))
