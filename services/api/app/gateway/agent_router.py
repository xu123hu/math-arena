"""Agent 路由网关（gateway/agent_router.py）

SSE 主入口 + 会话管理端点。
依赖方向：gateway → kernel → providers，单向。
"""

import json
import time
import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.auth import get_current_user
from app.gateway.schemas import ApiResponse
from app.kernel.context import ContextAssembler
from app.kernel.guard import Guard
from app.kernel.router import route as kernel_route
from app.models.ai_call import AICall
from app.models.conversation import Conversation
from app.models.database import get_db
from app.models.message import Message
from app.skills.chat import ChatSkill

logger = structlog.get_logger()

router = APIRouter()

# 全局实例
_context_assembler = ContextAssembler()
_chat_skill = ChatSkill()
_guard = Guard()


# ========== Pydantic schemas（对齐 API 文档 §4.1 / §4.3） ==========


class ChatContext(BaseModel):
    """聊天请求上下文（API 文档 §4.1）"""

    page: str | None = None
    workspace: str = "student"
    client_msg_id: str = Field(..., min_length=1, max_length=64)


class ChatRequest(BaseModel):
    """聊天请求体（对齐 API 文档 §4.1）"""

    conversation_id: str | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    context: ChatContext


class CreateConversationRequest(BaseModel):
    """创建会话请求体（对齐 API 文档 §4.3）"""

    workspace: str = "student"


# ========== POST /chat — SSE 主入口 ==========


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话主入口（协议见手册 §4.3，API 文档 §4.1）"""
    user_id = current_user["sub"]
    active_role = current_user.get("active_role", "student")
    request_id = str(uuid.uuid4())
    log = logger.bind(request_id=request_id, user_id=user_id)

    client_msg_id = body.context.client_msg_id

    # ② guard.check_input（手册 §7.7 步骤②）
    guard_result = await _guard.check_input(body.message, {"user_id": user_id})
    user_message = guard_result.cleaned_message

    # 1. 幂等检查：全局查询该 client_msg_id 是否已存在（手册 §6.2）
    #    必须在创建/查找会话之前执行，否则新会话内查不到已有消息
    existing_result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Message.client_msg_id == client_msg_id,
            Message.deleted_at.is_(None),
        )
    )
    existing_msg = existing_result.scalar_one_or_none()
    if existing_msg is not None:
        # 已存在 → SSE 重放已存信封（手册 §6.2）
        replay_conv_id = str(existing_msg.conversation_id)
        log.info("message.idempotent_replay", client_msg_id=client_msg_id)
        envelope = existing_msg.envelope or {
            "msg_id": str(existing_msg.id),
            "role": "assistant",
            "blocks": [{"type": "markdown", "content": existing_msg.content or ""}],
            "meta": {
                "skill": existing_msg.skill_id or "chat",
                "confidence": 1.0,
                "provider": "deepseek",
                "latency_ms": 0,
                "ai_generated": True,
            },
        }

        async def replay_stream():
            # 重放 meta 事件
            yield _format_sse(
                "meta",
                {
                    "conversation_id": replay_conv_id,
                    "msg_id": envelope.get("msg_id", str(existing_msg.id)),
                    "skill": envelope.get("meta", {}).get("skill", "chat"),
                    "confidence": envelope.get("meta", {}).get("confidence", 1.0),
                    "provider": envelope.get("meta", {}).get("provider", "deepseek"),
                },
            )
            # 重放 token 事件（完整内容）
            if existing_msg.content:
                yield _format_sse("token", {"text": existing_msg.content})
            # 重放 done 事件
            yield _format_sse(
                "done",
                {
                    "usage": {"tokens_in": 0, "tokens_out": 0},
                    "latency_ms": envelope.get("meta", {}).get("latency_ms", 0),
                },
            )

        return StreamingResponse(
            replay_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-Id": request_id,
                "X-Idempotent-Replay": "true",
            },
        )

    # 2. 会话处理：无 conversation_id 则创建新会话
    conversation_id = body.conversation_id
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

    # 3. 保存用户消息
    msg_id = str(uuid.uuid4())
    user_envelope = {
        "msg_id": msg_id,
        "role": "user",
        "blocks": [{"type": "markdown", "content": user_message}],
        "meta": {
            "skill": "chat",
            "confidence": 1.0,
            "provider": "deepseek",
            "latency_ms": 0,
            "ai_generated": False,
        },
    }

    user_msg = Message(
        conversation_id=conversation_id,
        client_msg_id=client_msg_id,
        role="user",
        content=user_message,
        envelope=user_envelope,
        skill_id="chat",
    )
    db.add(user_msg)
    try:
        await db.flush()
    except IntegrityError:
        # 并发幂等兜底：回滚后重放
        await db.rollback()
        result = await db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_msg_id == client_msg_id,
                Message.deleted_at.is_(None),
            )
        )
        existing = result.scalar_one_or_none()
        if existing and existing.role == "user":
            log.info("message.idempotent_concurrent", client_msg_id=client_msg_id)
            # 返回 40901 表示消息已在处理中
            return _sse_error(40901, "消息已在处理中")

    # 4. 更新会话消息计数
    await db.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(message_count=Conversation.message_count + 1)
    )
    await db.flush()

    # 5. 内核路由
    decision = await kernel_route(user_message, {"user_id": user_id})

    # 6. 上下文装配
    llm_messages = await _context_assembler.assemble(
        db=db,
        conversation_id=conversation_id,
        user_message=user_message,
    )

    # 7. 返回 SSE 流
    async def event_stream():
        nonlocal msg_id
        t_start = time.monotonic()
        assistant_msg_id = str(uuid.uuid4())
        full_text = ""
        provider_name = "deepseek"
        error_occurred = False

        try:
            # SSE: meta 事件（永远第一个）
            yield _format_sse(
                "meta",
                {
                    "conversation_id": conversation_id,
                    "msg_id": assistant_msg_id,
                    "skill": decision.skill_id,
                    "confidence": decision.confidence,
                    "provider": provider_name,
                },
            )

            # SSE: status 事件
            yield _format_sse("status", {"stage": "thinking", "text": "正在思考..."})

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
                    yield _format_sse("error", event["data"])
                    break

                # token 事件 — 直接传 data 内容（协议 §4.3）
                yield _format_sse(event["type"], event["data"])

            if not error_occurred:
                latency_ms = int((time.monotonic() - t_start) * 1000)

                # ⑥ guard.check_output（手册 §7.7 步骤⑥）
                full_text = await _guard.check_output(full_text, {"user_id": user_id})

                # SSE: done 事件
                yield _format_sse(
                    "done",
                    {
                        "usage": {
                            "tokens_in": _estimate_tokens_input(llm_messages),
                            "tokens_out": _estimate_tokens_output(full_text),
                        },
                        "latency_ms": latency_ms,
                    },
                )

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
                            user_message[:20],
                        ),
                    )
                )

                # 记录 ai_calls 流水
                ai_call = AICall(
                    request_id=request_id,
                    scene="chat",
                    provider=provider_name,
                    model=_get_model_name(provider_name),
                    input_tokens=_estimate_tokens_input(llm_messages),
                    output_tokens=_estimate_tokens_output(full_text),
                    latency_ms=latency_ms,
                    status="success",
                )
                db.add(ai_call)
                await db.flush()

                log.info(
                    "chat.done",
                    conversation_id=conversation_id,
                    provider=provider_name,
                    latency_ms=latency_ms,
                    output_len=len(full_text),
                )

        except Exception as e:
            log.exception("chat.stream.error")
            if not error_occurred:
                err_data = {"code": 50001, "message": str(e), "recoverable": False}
                yield _format_sse("error", err_data)

            # 记录失败的 ai_call
            ai_call = AICall(
                request_id=request_id,
                scene="chat",
                provider=provider_name,
                model=_get_model_name(provider_name),
                input_tokens=_estimate_tokens_input(llm_messages),
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
    """创建新空会话（API 文档 §4.3）"""
    user_id = current_user["sub"]
    active_role = body.workspace or current_user.get("active_role", "student")

    conv = Conversation(
        user_id=user_id,
        active_role=active_role,
        title="新对话",
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
        cursor_result = await db.execute(select(Message.created_at).where(Message.id == before))
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
    """格式化 SSE 事件（协议 §4.3）

    格式：event: <type>\ndata: <json>\n\n
    data 行直接是事件内容，不嵌套 type/data 包装。
    """
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_error(code: int, message: str, status_code: int = 200):
    """返回 SSE 错误响应"""
    err_data = {"code": code, "message": message, "recoverable": False}

    async def error_stream():
        yield _format_sse("error", err_data)

    return StreamingResponse(
        error_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Request-Id": str(uuid.uuid4())},
    )


def _estimate_tokens_input(messages: list[dict]) -> int:
    """估算输入 token 数（粗略：中文 ~1.5 字符/token，英文 ~4 字符/token）

    使用混合估算：总字符数 / 2.5 作为近似值。
    实际精确值需要 tiktoken 或 provider 返回的 usage。
    """
    total_chars = sum(len(m.get("content", "")) for m in messages)
    return max(1, int(total_chars / 2.5))


def _estimate_tokens_output(text: str) -> int:
    """估算输出 token 数"""
    return max(1, int(len(text) / 2.5))


def _get_model_name(provider: str) -> str:
    """根据 provider 返回模型名称"""
    if provider == "spark":
        return "spark-ultra"
    return "deepseek-v4-flash"
