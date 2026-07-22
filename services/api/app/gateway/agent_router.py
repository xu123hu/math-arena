"""Agent 路由网关（gateway/agent_router.py）

SSE 主入口 + 会话管理端点。
依赖方向：gateway → kernel → providers，单向。
"""

import json
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from app.gateway.auth import get_current_user
from app.gateway.schemas import ApiResponse
from app.kernel.context import ContextAssembler
from app.kernel.router import route as kernel_route
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.ai_call import AICall
from app.models.database import get_db
from app.skills.chat import ChatSkill

logger = structlog.get_logger()

router = APIRouter()

# 全局实例
_context_assembler = ContextAssembler()
_chat_skill = ChatSkill()


# ========== Pydantic schemas ==========

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """聊天请求体"""
    conversationId: str | None = None
    content: str = Field(..., min_length=1, max_length=4000)
    clientMsgId: str = Field(..., min_length=1, max_length=64)
    skill: str | None = None


class CreateConversationRequest(BaseModel):
    """创建会话请求体"""
    title: str | None = None
    activeRole: str | None = None


# ========== POST /chat — SSE 主入口 ==========

@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话主入口"""
    user_id = current_user["sub"]
    active_role = current_user.get("active_role", "student")
    request_id = str(uuid.uuid4())
    log = logger.bind(request_id=request_id, user_id=user_id)

    # 1. 会话处理：无 conversationId 则创建新会话
    conversation_id = body.conversationId
    if not conversation_id:
        conv = Conversation(
            user_id=user_id,
            active_role=active_role,
            title="新对话",
        )
        db.add(conv)
        await db.flush()
        conversation_id = str(conv.id)
        log.info("conversation.created", conversation_id=conversation_id)
    else:
        # 验证会话归属
        result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            return _sse_error(40401, "会话不存在", status_code=404)

    # 2. 保存用户消息（幂等）
    msg_id = str(uuid.uuid4())
    user_envelope = {
        "msg_id": msg_id,
        "role": "user",
        "blocks": [{"type": "markdown", "content": body.content}],
        "meta": {
            "skill": body.skill or "chat",
            "confidence": 1.0,
            "provider": "deepseek",
            "latency_ms": 0,
            "ai_generated": False,
        },
    }

    user_msg = Message(
        conversation_id=conversation_id,
        client_msg_id=body.clientMsgId,
        role="user",
        content=body.content,
        envelope=user_envelope,
        skill_id=body.skill or "chat",
    )
    db.add(user_msg)
    try:
        await db.flush()
    except IntegrityError:
        # 幂等：重复提交，查找已有消息
        await db.rollback()
        result = await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_msg_id == body.clientMsgId,
                Message.deleted_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            msg_id = str(existing.id)
        log.info("message.idempotent", client_msg_id=body.clientMsgId)

    # 3. 更新会话消息计数
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(message_count=Conversation.message_count + 1)
    )
    await db.flush()

    # 4. 内核路由（M0 简化：全部走 chat）
    decision = await kernel_route(body.content, {"user_id": user_id})

    # 5. 上下文装配
    llm_messages = await _context_assembler.assemble(
        db=db,
        conversation_id=conversation_id,
        user_message=body.content,
    )

    # 6. 返回 SSE 流
    async def event_stream():
        nonlocal msg_id
        t_start = time.monotonic()
        assistant_msg_id = str(uuid.uuid4())
        full_text = ""
        provider_name = "deepseek"
        error_occurred = False

        try:
            # SSE: meta 事件（永远第一个）
            meta_data = {
                "type": "meta",
                "data": {
                    "conversation_id": conversation_id,
                    "msg_id": assistant_msg_id,
                    "skill": decision.skill_id,
                    "confidence": decision.confidence,
                    "provider": provider_name,
                },
            }
            yield _format_sse("meta", meta_data)

            # SSE: status 事件（思考中）
            status_data = {
                "type": "status",
                "data": {"stage": "thinking", "text": "正在思考..."},
            }
            yield _format_sse("status", status_data)

            # 调用 chat skill 流式生成
            async for event in _chat_skill.run(
                {"messages": llm_messages, "request_id": request_id},
                {"user_id": user_id, "conversation_id": conversation_id},
            ):
                if event["type"] == "_result_meta":
                    # 内部元信息，不推送给前端
                    provider_name = event["data"].get("provider", "deepseek")
                    full_text = event["data"].get("full_text", full_text)
                    continue

                if event["type"] == "error":
                    error_occurred = True
                    yield _format_sse("error", event)
                    break

                # token 事件
                yield _format_sse(event["type"], event)

            if not error_occurred:
                latency_ms = int((time.monotonic() - t_start) * 1000)

                # SSE: done 事件
                done_data = {
                    "type": "done",
                    "data": {
                        "usage": {
                            "tokens_in": len(body.content) // 2,
                            "tokens_out": len(full_text) // 2,
                        },
                        "latency_ms": latency_ms,
                    },
                }
                yield _format_sse("done", done_data)

                # 保存助手回复到 messages 表
                assistant_envelope = {
                    "msg_id": assistant_msg_id,
                    "role": "assistant",
                    "blocks": [{"type": "markdown", "content": full_text}],
                    "meta": {
                        "skill": decision.skill_id,
                        "confidence": decision.confidence,
                        "provider": provider_name,
                        "latency_ms": latency_ms,
                        "ai_generated": True,
                    },
                }

                assistant_msg = Message(
                    conversation_id=conversation_id,
                    client_msg_id=f"ai_{assistant_msg_id}",
                    role="assistant",
                    content=full_text,
                    envelope=assistant_envelope,
                    skill_id=decision.skill_id,
                    route_info={"confidence": decision.confidence},
                )
                db.add(assistant_msg)

                # 更新会话消息计数和标题（首次对话自动取标题）
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(
                        message_count=Conversation.message_count + 1,
                        title=func.coalesce(
                            func.nullif(Conversation.title, "新对话"),
                            body.content[:20],
                        ),
                    )
                )

                # 记录 ai_calls 流水
                ai_call = AICall(
                    request_id=request_id,
                    scene="chat",
                    provider=provider_name,
                    model="deepseek-v4-flash",
                    input_tokens=len(body.content) // 2,
                    output_tokens=len(full_text) // 2,
                    latency_ms=latency_ms,
                    status="ok",
                )
                db.add(ai_call)
                await db.flush()

                log.info(
                    "chat.done",
                    conversation_id=conversation_id,
                    latency_ms=latency_ms,
                    output_len=len(full_text),
                )

        except Exception as e:
            log.exception("chat.stream.error")
            if not error_occurred:
                err_data = {
                    "type": "error",
                    "data": {"code": 50001, "message": str(e), "recoverable": False},
                }
                yield _format_sse("error", err_data)

            # 记录失败的 ai_call
            ai_call = AICall(
                request_id=request_id,
                scene="chat",
                provider=provider_name,
                model="deepseek-v4-flash",
                input_tokens=len(body.content) // 2,
                output_tokens=0,
                latency_ms=int((time.monotonic() - t_start) * 1000),
                status="error",
                error=str(e)[:500],
            )
            db.add(ai_call)
            await db.flush()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


# ========== GET /conversations ==========

@router.get("/conversations")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前用户的会话列表"""
    user_id = current_user["sub"]

    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    conversations = result.scalars().all()

    # 总数
    count_result = await db.execute(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    total = count_result.scalar() or 0

    items = [
        {
            "id": str(c.id),
            "title": c.title,
            "activeRole": c.active_role,
            "summary": c.summary,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]

    return ApiResponse(code=0, message="ok", data={"items": items, "total": total})


# ========== POST /conversations ==========

@router.post("/conversations")
async def create_conversation(
    body: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新空会话"""
    user_id = current_user["sub"]
    active_role = body.activeRole or current_user.get("active_role", "student")

    conv = Conversation(
        user_id=user_id,
        active_role=active_role,
        title=body.title or "新对话",
    )
    db.add(conv)
    await db.flush()

    return ApiResponse(
        code=0,
        message="ok",
        data={
            "id": str(conv.id),
            "title": conv.title,
            "activeRole": conv.active_role,
            "createdAt": conv.created_at.isoformat() if conv.created_at else None,
        },
    )


# ========== GET /conversations/{id}/messages ==========

@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    limit: int = 20,
    before: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定会话的历史消息（倒序分页）"""
    user_id = current_user["sub"]

    # 验证会话归属
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        return ApiResponse(code=40401, message="会话不存在")

    # 查询消息
    query = (
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.deleted_at.is_(None),
        )
        .order_by(Message.created_at.desc())
        .limit(limit + 1)  # 多取一条判断 hasMore
    )

    if before:
        # 游标分页：获取 before 对应消息的 created_at
        cursor_result = await db.execute(
            select(Message.created_at).where(Message.id == before)
        )
        cursor_time = cursor_result.scalar()
        if cursor_time:
            query = query.where(Message.created_at < cursor_time)

    result = await db.execute(query)
    rows = result.scalars().all()

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    items = [
        {
            "id": str(m.id),
            "role": m.role,
            "envelope": m.envelope,
            "clientMsgId": m.client_msg_id,
            "createdAt": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]

    return ApiResponse(code=0, message="ok", data={"items": items, "hasMore": has_more})


# ========== 工具函数 ==========

def _format_sse(event_type: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_error(code: int, message: str, status_code: int = 200):
    """返回 SSE 错误响应"""
    err_data = {
        "type": "error",
        "data": {"code": code, "message": message, "recoverable": False},
    }
    async def error_stream():
        yield _format_sse("error", err_data)

    return StreamingResponse(
        error_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Request-Id": str(uuid.uuid4())},
    )
