"""班级域路由（domains/classroom/router.py）

6 个 API 端点 + 权限控制（§5.2）。
越权规则：非本班教师→40302；学生confirm→40301；跨班读→404。
"""

import random

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.auth import get_current_user
from app.gateway.schemas import ApiResponse
from app.models.class_ import Class
from app.models.class_member import ClassMember
from app.models.database import get_db
from app.models.role_binding import RoleBinding

logger = structlog.get_logger()
router = APIRouter()

# 班级码字符集（排除 0/O/1/I，ADR-001-6）
CODE_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def _generate_invite_code() -> str:
    """生成 6 位班级码"""
    return "".join(random.choices(CODE_CHARSET, k=CODE_LENGTH))


# ========== Schemas ==========


class CreateClassRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    grade: str | None = None


class JoinClassRequest(BaseModel):
    invite_code: str = Field(..., min_length=6, max_length=8)
    nickname: str | None = None


class ConfirmMemberRequest(BaseModel):
    confirmed: bool = True


# ========== POST / — 教师建班 ==========


@router.post("")
@router.post("/", include_in_schema=False)
async def create_class(
    body: CreateClassRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """教师建班，自动生成班级码"""
    user_id = current_user["sub"]

    # 验证教师角色
    role_result = await db.execute(
        select(RoleBinding).where(
            RoleBinding.user_id == user_id,
            RoleBinding.role == "teacher",
            RoleBinding.deleted_at.is_(None),
        )
    )
    if role_result.scalar_one_or_none() is None:
        return ApiResponse(code=40301, message="仅教师可以建班")

    # 生成唯一班级码（撞库重试）
    for _ in range(10):
        code = _generate_invite_code()
        existing = await db.execute(select(Class).where(Class.invite_code == code))
        if existing.scalar_one_or_none() is None:
            break
    else:
        return ApiResponse(code=50001, message="班级码生成失败，请重试")

    new_class = Class(
        name=body.name,
        invite_code=code,
        owner_id=user_id,
        grade=body.grade or "",
        subject="math",
    )
    db.add(new_class)
    await db.flush()

    # 创建者自动加入为教师成员
    member = ClassMember(
        class_id=new_class.id,
        user_id=user_id,
        member_role="teacher",
        confirmed=True,
        join_via="create",
    )
    db.add(member)
    await db.flush()

    logger.info("class.created", class_id=str(new_class.id), owner=user_id)
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "id": str(new_class.id),
            "name": new_class.name,
            "inviteCode": code,
            "grade": new_class.grade,
        },
    )


# ========== POST /join — 学生申请加入 ==========


@router.post("/join")
async def join_class(
    body: JoinClassRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """学生申请加入班级（confirmed=false，待确认）"""
    user_id = current_user["sub"]

    # 查找班级
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

    # 检查是否已加入/已申请
    existing = await db.execute(
        select(ClassMember).where(
            ClassMember.class_id == target_class.id,
            ClassMember.user_id == user_id,
            ClassMember.deleted_at.is_(None),
        )
    )
    if existing.scalar_one_or_none() is not None:
        return ApiResponse(code=40902, message="已申请或已在班级中")

    # 创建待确认成员
    member = ClassMember(
        class_id=target_class.id,
        user_id=user_id,
        member_role="student",
        confirmed=False,
        join_via="code",
        nickname_in_class=body.nickname or "",
    )
    db.add(member)
    await db.flush()

    logger.info("class.joined", class_id=str(target_class.id), user=user_id)
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "classId": str(target_class.id),
            "className": target_class.name,
            "status": "pending",
        },
    )


# ========== GET /mine — 我的班级列表 ==========


@router.get("/mine")
async def my_classes(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我任教/加入的班级列表"""
    user_id = current_user["sub"]

    result = await db.execute(
        select(Class, ClassMember)
        .join(ClassMember, Class.id == ClassMember.class_id)
        .where(
            ClassMember.user_id == user_id,
            ClassMember.deleted_at.is_(None),
            Class.deleted_at.is_(None),
        )
        .order_by(Class.created_at.desc())
    )
    rows = result.all()

    items = []
    for cls, member in rows:
        items.append(
            {
                "id": str(cls.id),
                "name": cls.name,
                "grade": cls.grade,
                "myRole": member.member_role,
                "confirmed": member.confirmed,
                "inviteCode": cls.invite_code if member.member_role == "teacher" else None,
                "createdAt": cls.created_at.isoformat() if cls.created_at else None,
            }
        )

    return ApiResponse(code=0, message="ok", data={"items": items, "total": len(items)})


# ========== GET /{id}/members — 成员列表 ==========


@router.get("/{class_id}/members")
async def list_members(
    class_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """成员列表（教师见全量含待确认，学生只见已确认）"""
    user_id = current_user["sub"]

    # 验证班级存在
    cls_result = await db.execute(
        select(Class).where(Class.id == class_id, Class.deleted_at.is_(None))
    )
    target_class = cls_result.scalar_one_or_none()
    if target_class is None:
        return ApiResponse(code=40401, message="班级不存在")

    # 验证当前用户是该班成员
    my_member_result = await db.execute(
        select(ClassMember).where(
            ClassMember.class_id == class_id,
            ClassMember.user_id == user_id,
            ClassMember.deleted_at.is_(None),
        )
    )
    my_member = my_member_result.scalar_one_or_none()
    if my_member is None:
        # 非本班成员 → 404（不泄露存在性）
        return ApiResponse(code=40401, message="班级不存在")

    # 查询成员
    query = select(ClassMember).where(
        ClassMember.class_id == class_id, ClassMember.deleted_at.is_(None)
    )

    # 学生只见 confirmed=true
    if my_member.member_role == "student":
        query = query.where(ClassMember.confirmed.is_(True))

    result = await db.execute(query.order_by(ClassMember.joined_at.desc()))
    members = result.scalars().all()

    items = []
    for m in members:
        item = {
            "id": str(m.id),
            "userId": str(m.user_id),
            "memberRole": m.member_role,
            "confirmed": m.confirmed,
            "joinVia": m.join_via,
            "nicknameInClass": m.nickname_in_class or "",
            "joinedAt": m.joined_at.isoformat() if m.joined_at else None,
        }
        items.append(item)

    return ApiResponse(code=0, message="ok", data={"items": items, "total": len(items)})


# ========== PATCH /{id}/members/{uid} — 教师确认入班 ==========


@router.patch("/{class_id}/members/{member_user_id}")
async def confirm_member(
    class_id: str,
    member_user_id: str,
    body: ConfirmMemberRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """教师确认/取消确认成员"""
    user_id = current_user["sub"]

    # 验证当前用户是该班教师
    my_result = await db.execute(
        select(ClassMember).where(
            ClassMember.class_id == class_id,
            ClassMember.user_id == user_id,
            ClassMember.member_role == "teacher",
            ClassMember.deleted_at.is_(None),
        )
    )
    if my_result.scalar_one_or_none() is None:
        # 学生尝试 confirm → 40301
        return ApiResponse(code=40301, message="仅教师可以确认成员")

    # 查找目标成员
    target_result = await db.execute(
        select(ClassMember).where(
            ClassMember.class_id == class_id,
            ClassMember.user_id == member_user_id,
            ClassMember.deleted_at.is_(None),
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        return ApiResponse(code=40401, message="成员不存在")

    target.confirmed = body.confirmed
    await db.flush()

    logger.info(
        "class.member_confirmed", class_id=class_id, member=member_user_id, confirmed=body.confirmed
    )
    return ApiResponse(code=0, message="ok", data={"confirmed": body.confirmed})


# ========== POST /{id}/invite-code/reset — 重置班级码 ==========


@router.post("/{class_id}/invite-code/reset")
async def reset_invite_code(
    class_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """重置班级码（旧码立即失效）"""
    user_id = current_user["sub"]

    # 验证是该班教师
    cls_result = await db.execute(
        select(Class).where(
            Class.id == class_id,
            Class.owner_id == user_id,
            Class.deleted_at.is_(None),
        )
    )
    target_class = cls_result.scalar_one_or_none()
    if target_class is None:
        return ApiResponse(code=40302, message="仅班级创建教师可以重置班级码")

    # 生成新码
    for _ in range(10):
        new_code = _generate_invite_code()
        existing = await db.execute(
            select(Class).where(Class.invite_code == new_code, Class.id != class_id)
        )
        if existing.scalar_one_or_none() is None:
            break

    target_class.invite_code = new_code
    await db.flush()

    logger.info("class.code_reset", class_id=class_id)
    return ApiResponse(code=0, message="ok", data={"inviteCode": new_code})
