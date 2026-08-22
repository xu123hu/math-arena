"""认证路由

实现 /api/auth/* 系列端点（API 文档 §2）。
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domains.identity.sessions import SessionService, set_session_cookies
from app.domains.identity.types import CurrentIdentity
from app.gateway import redis as redis_util
from app.gateway.auth import get_current_user
from app.gateway.jwt import create_token_with_role
from app.gateway.schemas import (
    ApiResponse,
    LoginData,
    LoginRequest,
    RoleInfo,
    RoleSwitchRequest,
    SmsCodeData,
    SmsCodeRequest,
    UserData,
)
from app.models.database import get_db
from app.models.identity import AuthSession
from app.models.role_binding import RoleBinding
from app.models.user import User

logger = structlog.get_logger()

router = APIRouter()


# ========== POST /sms-code ==========


@router.post("/sms-code", response_model=ApiResponse)
async def send_sms_code(body: SmsCodeRequest, response: Response):
    """发送短信验证码（非生产环境固定 123456）"""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 05 Sep 2026 00:00:00 GMT"
    logger.warning("auth.legacy_endpoint", endpoint="sms-code")
    # 生产环境未接入真实短信通道前拒绝发送，防止 mock 验证码流入线上
    if settings.app_env == "production":
        return ApiResponse(code=50301, message="短信服务未配置，暂不可用")

    # 检查发送频率限制
    can_send = await redis_util.check_sms_rate_limit(body.phone)
    if not can_send:
        return ApiResponse(code=42901, message="发送频率过快，请 60 秒后重试")

    # 非生产环境使用固定验证码
    code = settings.dev_sms_code
    await redis_util.set_sms_code(body.phone, code)

    return ApiResponse(code=0, message="sent", data=SmsCodeData(ttl=redis_util.SMS_CODE_TTL))


# ========== POST /login ==========


@router.post("/login", response_model=ApiResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """验证码登录（新用户自动注册）"""
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "Sat, 05 Sep 2026 00:00:00 GMT"
    logger.warning("auth.legacy_endpoint", endpoint="login")
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
        role_binding = RoleBinding(user_id=user.id, role="student", verified=True)
        db.add(role_binding)
        await db.flush()

    # admin 引导：手机号命中 ADMIN_PHONES 白名单且无 admin 绑定时自动创建，
    # 使本次签发 JWT 的 roles 含 admin（/api/auth/role/apply 仍禁止自助申请 admin，
    # 白名单是唯一的 admin 运维通道）
    if user.phone in settings.admin_phone_list:
        admin_result = await db.execute(
            select(RoleBinding).where(
                RoleBinding.user_id == user.id,
                RoleBinding.role == "admin",
                RoleBinding.deleted_at.is_(None),
            )
        )
        if admin_result.scalar_one_or_none() is None:
            db.add(RoleBinding(user_id=user.id, role="admin", verified=True))
            await db.flush()
            logger.info("auth.admin_bootstrapped", user_id=str(user.id))

    # 查询用户所有角色
    roles_result = await db.execute(
        select(RoleBinding).where(
            RoleBinding.user_id == user.id,
            RoleBinding.status == "approved",
            RoleBinding.deleted_at.is_(None),
        )
    )
    role_bindings = roles_result.scalars().all()
    roles_list = [
        RoleInfo(role=rb.role, verified=rb.verified, org_name=rb.org_name) for rb in role_bindings
    ]
    role_names = [rb.role for rb in role_bindings]

    # 默认激活第一个角色
    active_role = role_names[0] if role_names else "student"

    # 兼容响应仍返回 data.token，但底层必须使用可撤销的新会话模型。
    issued = await SessionService(
        refresh_pepper=settings.auth_refresh_token_pepper
    ).issue(
        db,
        user,
        active_role,
        remember=False,
    )
    set_session_cookies(
        response,
        issued,
        secure=settings.app_env == "production",
    )

    user_data = UserData(
        id=str(user.id),
        nickname=user.nickname or "",
        active_role=active_role,
        roles=roles_list,
        is_new=is_new,
    )

    return ApiResponse(
        code=0,
        message="ok",
        data=LoginData(token=issued.access_token, user=user_data),
    )


# ========== GET /me ==========


@router.get("/me", response_model=ApiResponse)
async def get_me(
    current_user: CurrentIdentity = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """获取当前用户信息"""
    user_id = current_user.user_id

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
    active_role = current_user.active_role

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "id": str(user.id),
            "nickname": user.nickname or "",
            "avatar_url": user.avatar_url,
            "status": user.status,
            "onboarding_status": user.onboarding_status,
            "active_role": active_role,
            "roles": [
                {
                    "role": rb.role,
                    "status": rb.status,
                    "verified": rb.verified,
                    "org_name": rb.org_name,
                }
                for rb in role_bindings
            ],
        },
    )


# ========== POST /role/switch ==========


@router.post("/role/switch", response_model=ApiResponse)
async def switch_role(
    body: RoleSwitchRequest,
    current_user: CurrentIdentity = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """切换角色（换发 JWT）"""
    user_id = current_user.user_id
    target_role = body.role

    # 查询用户在该角色上的绑定
    result = await db.execute(
        select(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role == target_role,
            RoleBinding.status == "approved",
            RoleBinding.deleted_at.is_(None),
        )
    )
    role_binding = result.scalar_one_or_none()

    if role_binding is None:
        raise HTTPException(
            status_code=403,
            detail={"code": 40301, "error_key": "AUTH_ROLE_NOT_APPROVED", "message": f"{target_role} 身份尚未获批或已停用"},
        )
    if current_user.session_id is None:
        raise HTTPException(
            status_code=401,
            detail={"code": 40100, "error_key": "AUTH_SESSION_REQUIRED", "message": "请重新登录后切换身份"},
        )
    auth_session = await db.scalar(
        select(AuthSession).where(AuthSession.id == current_user.session_id).with_for_update()
    )
    if auth_session is None or auth_session.revoked_at is not None:
        raise HTTPException(
            status_code=401,
            detail={"code": 40100, "error_key": "AUTH_SESSION_REVOKED", "message": "会话已失效"},
        )
    user = await db.get(User, user_id)
    auth_session.active_role = target_role
    user.last_active_role = target_role
    token = create_token_with_role(
        user_id=str(user_id),
        role=target_role,
        session_id=str(auth_session.id),
        security_version=user.security_version,
    )
    return ApiResponse(
        code=0,
        message="ok",
        data={"access_token": token, "token": token, "expires_in": 900},
    )


# ========== POST /login-by-code — 班级码免密首登 ==========


class LoginByCodeRequest(BaseModel):
    invite_code: str = Field(..., min_length=6, max_length=8)
    nickname: str = Field(default="", max_length=64)


@router.post("/login-by-code", response_model=ApiResponse)
async def login_by_code(body: LoginByCodeRequest, db: AsyncSession = Depends(get_db)):
    """班级码免密首登（学生通过班级码直接注册+登录）"""
    raise HTTPException(
        status_code=410,
        detail={
            "code": 41001,
            "error_key": "AUTH_CLASS_CODE_LOGIN_DEPRECATED",
            "message": "班级码免密登录已停用，请先通过手机号登录后再加入班级",
        },
        headers={"Deprecation": "true", "Sunset": "Sat, 05 Sep 2026 00:00:00 GMT"},
    )

    from app.models.class_ import Class
    from app.models.class_member import ClassMember

    # 班级码尝试限流（防撞库）
    if not await redis_util.check_class_code_rate(body.invite_code):
        return ApiResponse(code=42901, message="尝试过于频繁，请稍后再试")

    # 验证班级码有效
    result = await db.execute(
        select(Class).where(
            Class.invite_code == body.invite_code,
            Class.deleted_at.is_(None),
            Class.status == "active",
        )
    )
    target_class = result.scalar_one_or_none()
    if target_class is None:
        return ApiResponse(code=40003, message="班级码不存在或已失效")

    # 创建新用户（免密）
    import uuid as uuid_mod

    random_phone = f"class_{uuid_mod.uuid4().hex[:12]}"
    user = User(phone=random_phone, nickname=body.nickname or "学生")
    db.add(user)
    await db.flush()

    # 创建默认角色绑定 student
    role_binding = RoleBinding(user_id=user.id, role="student", verified=True)
    db.add(role_binding)

    # 自动加入班级（confirmed=false，待教师确认）
    member = ClassMember(
        class_id=target_class.id,
        user_id=user.id,
        member_role="student",
        confirmed=False,
        join_via="code_first_login",
        nickname_in_class=body.nickname or "",
    )
    db.add(member)
    await db.flush()

    # 签发 JWT
    token = create_token_with_role(
        user_id=str(user.id),
        role="student",
        roles=["student"],
        verified=True,
    )

    user_data = UserData(
        id=str(user.id),
        nickname=user.nickname or "",
        active_role="student",
        roles=[RoleInfo(role="student", verified=True, org_name=None)],
        is_new=True,
    )

    return ApiResponse(code=0, message="ok", data=LoginData(token=token, user=user_data))


# ========== POST /register/teacher — 教师注册（待审核） ==========


class RegisterTeacherRequest(BaseModel):
    phone: str = Field(..., min_length=11, max_length=20)
    code: str = Field(..., min_length=4, max_length=6)
    name: str = Field(..., min_length=1, max_length=64)
    school: str = Field(default="", max_length=128)


@router.post("/register/teacher", response_model=ApiResponse)
async def register_teacher(body: RegisterTeacherRequest, db: AsyncSession = Depends(get_db)):
    """教师注册（待审核状态，需管理员确认后 verified=true）"""
    # 验证验证码
    stored_code = await redis_util.get_sms_code(body.phone)
    if stored_code is None:
        return ApiResponse(code=40002, message="验证码已过期，请重新获取")
    if stored_code != body.code:
        return ApiResponse(code=40002, message="验证码错误")

    await redis_util.delete_sms_code(body.phone)

    # 检查手机号是否已注册
    existing = await db.execute(
        select(User).where(User.phone == body.phone, User.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none() is not None:
        return ApiResponse(code=40901, message="该手机号已注册")

    # 创建用户
    user = User(phone=body.phone, nickname=body.name)
    db.add(user)
    await db.flush()

    # 创建教师角色绑定（verified=False，待审核）
    role_binding = RoleBinding(
        user_id=user.id,
        role="teacher",
        verified=False,
        org_name=body.school or None,
    )
    db.add(role_binding)

    # 同时创建 student 角色
    student_binding = RoleBinding(user_id=user.id, role="student", verified=True)
    db.add(student_binding)
    await db.flush()

    # 签发 JWT（默认 teacher 角色但未验证）
    token = create_token_with_role(
        user_id=str(user.id),
        role="teacher",
        roles=["teacher", "student"],
        verified=False,
    )

    user_data = UserData(
        id=str(user.id),
        nickname=user.nickname or "",
        active_role="teacher",
        roles=[
            RoleInfo(role="teacher", verified=False, org_name=body.school or None),
            RoleInfo(role="student", verified=True, org_name=None),
        ],
        is_new=True,
    )

    return ApiResponse(code=0, message="ok", data=LoginData(token=token, user=user_data))


# ========== POST /role/apply — 已登录用户申请角色绑定 ==========


class RoleApplyRequest(BaseModel):
    role: str = Field(..., pattern="^(teacher|researcher)$")
    org_name: str = Field(default="", max_length=128)


@router.post("/role/apply", response_model=ApiResponse)
async def apply_role(
    body: RoleApplyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """已登录用户申请角色绑定

    researcher / teacher：均创建待审核绑定，由管理员审核或邀请码批准
    重复绑定/重复申请 → 40901
    """
    user_id = current_user["sub"]

    # 重复绑定检查
    result = await db.execute(
        select(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role == body.role,
            RoleBinding.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is not None:
        return ApiResponse(code=40901, message=f"已绑定或已申请 {body.role} 角色")

    verified = False
    binding = RoleBinding(
        user_id=user_id,
        role=body.role,
        verified=verified,
        org_name=body.org_name or None,
    )
    db.add(binding)
    await db.flush()

    logger.info("auth.role_applied", user_id=user_id, role=body.role, verified=verified)
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "role": body.role,
            "verified": verified,
            "status": "pending",
        },
    )
