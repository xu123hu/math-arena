"""Agent 路由网关（gateway/agent_router.py）

SSE 主入口 + 会话管理端点。
完整实现手册 §7.7 请求主链路时序：
① 鉴权+幂等检查 → ② guard.check_input → ③ route → ④ clarify分支
→ ⑤ skill实例化+context装配 → ⑥ skill.run流式 → ⑦ guard.check_output
→ ⑧ 信封落库 + citation/badge/done → ⑨ 异步摘要/标题生成/skill_runs

关键纪律：
- 首字节 <100ms：进入生成器立刻发 SSE 注释 ": open"，路由等慢操作在其后
- 10s 无事件发 ": ping" 心跳（SSE 注释，不干扰事件流）
- 幂等键成对：user 消息 client_msg_id 原样，assistant 消息 "ai_" + client_msg_id
- done.usage 用 providers 透传的真实 token 计数（缺失时降级估算）
- ai_calls 由 providers 层 audit 统一落库，gateway 不再重复写
"""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.auth import get_current_user
from app.gateway.schemas import ApiResponse
from app.kernel.context import get_context_assembler
from app.kernel.guard import get_guard
from app.kernel.memory import get_memory_manager
from app.kernel.rag import get_rag_pipeline
from app.kernel.router import get_intent_router
from app.models.conversation import Conversation
from app.models.database import async_session_factory, get_db
from app.models.message import Message
from app.models.skill_run import SkillRun
from app.providers.router import get_model_router
from app.skills.base import SkillContext
from app.skills.registry import get_skill_registry

logger = structlog.get_logger()

router = APIRouter()

# 幂等重生成窗口：user 消息存在但无 assistant 完成态时，
# <180s 视为处理中（40901），>=180s 视为上次中断，复用 user 消息重生成
IDEMPOTENT_REUSE_SECONDS = 180
# SSE 心跳间隔（秒）：超过该时长无事件则发 ": ping"
SSE_HEARTBEAT_SECONDS = 10

# ========== SSE 并发连接限制 ==========
_MAX_CONCURRENT = 20  # 全局最大并发SSE连接
_MAX_PER_USER = 3  # 每用户最大并发SSE连接
_global_sse_semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
_user_sse_counts: dict[str, int] = {}


async def _check_sse_concurrency(
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> tuple[str, str]:
    """SSE 并发检查依赖（在 get_db 之前执行，拒绝时不占用 DB 连接）

    Returns:
        (user_id, request_id): 用户 ID 和请求 ID

    Raises:
        HTTPException: 429 超限
    """
    user_id = current_user["sub"]
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    if _global_sse_semaphore._value <= 0:
        logger.warning("chat.sse.global_limit_reached", active=_MAX_CONCURRENT)
        raise HTTPException(
            status_code=429,
            detail={
                "type": "error",
                "code": 42901,
                "message": "服务繁忙，请稍后重试",
                "requestId": request_id,
                "data": None,
                "traceId": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": "1.0.0",
            },
        )
    _user_count = _user_sse_counts.get(user_id, 0)
    if _user_count >= _MAX_PER_USER:
        logger.warning("chat.sse.user_limit_reached", user_id=user_id, active=_user_count)
        raise HTTPException(
            status_code=429,
            detail={
                "type": "error",
                "code": 42901,
                "message": "服务繁忙，请稍后重试",
                "requestId": request_id,
                "data": None,
                "traceId": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": "1.0.0",
            },
        )
    return user_id, request_id


TITLE_PROMPT = (
    "请根据用户的这条消息，为这段对话生成一个简短标题。"
    "要求：8~15个汉字，概括主题，不要标点符号和书名号，直接输出标题本身。\n"
    "用户消息：{message}"
)


# ========== Pydantic schemas ==========


class ChatContext(BaseModel):
    page: str | None = None
    workspace: str = "student"
    client_msg_id: str = Field(..., min_length=1, max_length=64)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(..., min_length=1, max_length=4000)
    context: ChatContext


class CreateConversationRequest(BaseModel):
    workspace: str = "student"


class FeedbackRequest(BaseModel):
    target_msg_id: str
    reason: str = ""


# ========== POST /chat — SSE 主入口（§7.7 完整时序）==========


@router.post("/chat")
async def chat(
    body: ChatRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: tuple = Depends(_check_sse_concurrency),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE 流式对话主入口"""
    user_id, request_id = user_id  # 依赖返回元组
    # 获取信号量槽位（并发检查已在依赖中完成）
    await _global_sse_semaphore.acquire()
    _user_sse_counts[user_id] = _user_sse_counts.get(user_id, 0) + 1

    # 变量初始化
    log = logger.bind(request_id=request_id, user_id=user_id)
    active_role = current_user.get("active_role", "student")
    client_msg_id = body.context.client_msg_id
    ai_client_msg_id = f"ai_{client_msg_id}"
    log.debug(
        "chat.sse.slot_acquired",
        global_remaining=_global_sse_semaphore._value,
        user_active=_user_sse_counts[user_id],
    )

    # ① 幂等检查（§6.2）：先查 assistant 完成态 → 完整信封重放
    done_result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Message.client_msg_id == ai_client_msg_id,
            Message.deleted_at.is_(None),
        )
    )
    done_msg = done_result.scalar_one_or_none()
    if done_msg is not None:
        log.info("message.idempotent_replay", client_msg_id=client_msg_id)
        _release_sse_slot(user_id)
        return _replay_response(done_msg, request_id)

    # 再查 user 消息（上一次请求可能中断在流式途中）
    user_result = await db.execute(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.user_id == user_id,
            Message.client_msg_id == client_msg_id,
            Message.role == "user",
            Message.deleted_at.is_(None),
        )
    )
    existing_user_msg = user_result.scalar_one_or_none()
    reused_user_msg: Message | None = None
    if existing_user_msg is not None:
        if _age_seconds(existing_user_msg.created_at) < IDEMPOTENT_REUSE_SECONDS:
            log.info("message.idempotent_processing", client_msg_id=client_msg_id)
            _release_sse_slot(user_id)
            return _sse_error_response(40901, "消息正在处理中，请勿重复发送", request_id)
        # 超过窗口期：视为上次中断，复用该 user 消息重新生成回答
        log.info("message.idempotent_regenerate", client_msg_id=client_msg_id)
        reused_user_msg = existing_user_msg

    conversation_id = body.conversation_id
    title_is_default = True
    guard = get_guard()

    if reused_user_msg is not None:
        # 复用路径：跳过 guard 与消息落库（首次请求已完成过）
        user_message = reused_user_msg.content
        conversation_id = str(reused_user_msg.conversation_id)
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
                Conversation.deleted_at.is_(None),
            )
        )
        conv = conv_result.scalar_one_or_none()
        if conv is None:
            _release_sse_slot(user_id)
            return _sse_error_response(40401, "会话不存在", request_id)
        title_is_default = (conv.title or "新对话") == "新对话"
    else:
        # ② guard.check_input
        guard_result = await guard.check_input(body.message, {"user_id": user_id})
        if not guard_result.safe:
            _release_sse_slot(user_id)
            return _sse_error_response(40001, guard_result.reason or "输入包含不当内容", request_id)
        user_message = guard_result.cleaned_message

        # 会话处理
        if not conversation_id:
            conv = Conversation(user_id=user_id, active_role=active_role, title="新对话")
            db.add(conv)
            await db.flush()
            conversation_id = str(conv.id)
        else:
            result = await db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                    Conversation.deleted_at.is_(None),
                )
            )
            conv = result.scalar_one_or_none()
            if conv is None:
                _release_sse_slot(user_id)
                return _sse_error_response(40401, "会话不存在", request_id)
            title_is_default = (conv.title or "新对话") == "新对话"

        # 保存用户消息
        user_msg = Message(
            conversation_id=conversation_id,
            client_msg_id=client_msg_id,
            role="user",
            content=user_message,
            envelope={
                "msg_id": str(uuid.uuid4()),
                "role": "user",
                "blocks": [{"type": "markdown", "content": user_message}],
            },
            skill_id="chat",
        )
        db.add(user_msg)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            _release_sse_slot(user_id)
            return _sse_error_response(40901, "消息已在处理中", request_id)

        # 更新消息计数
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(message_count=Conversation.message_count + 1)
        )
        await db.flush()
        # 关键：流式开始前显式提交——幂等 40901 保护与次轮会话查找
        # 都依赖已提交状态（依赖拆解时的 commit 排在后台任务之后，太迟）
        await db.commit()

    # ③~⑨ SSE 流式主链路
    model_router = get_model_router()
    intended_provider = model_router.intended_provider

    async def _cleanup_stream():
        """包装 event_stream，流结束后释放并发槽位"""
        try:
            async for chunk in event_stream():
                yield chunk
        finally:
            _global_sse_semaphore.release()
            _user_sse_counts[user_id] = max(0, _user_sse_counts.get(user_id, 1)) - 1
            if _user_sse_counts[user_id] == 0:
                del _user_sse_counts[user_id]
            log.debug(
                "chat.sse.slot_released",
                global_remaining=_global_sse_semaphore._value,
                user_active=_user_sse_counts.get(user_id, 0),
            )

    async def event_stream():
        try:
            t_start = time.monotonic()
            assistant_msg_id = str(uuid.uuid4())
            full_text = ""
            provider_name = intended_provider
            error_occurred = False
            result_meta: dict = {}
            skill_id = "chat"
            confidence = 0.5

            # 首字节纪律：立即发出 SSE 注释，客户端即刻收到响应头+首字节
            yield ": open\n\n"

            # ③ 意图路由（慢操作，放在首字节之后）
            intent_router = get_intent_router()
            decision = await intent_router.route(
                user_message,
                db=db,
                user_id=user_id,
                surface=body.context.page or "",
                request_id=request_id,
            )
            skill_id = decision.skill_id
            confidence = decision.confidence

            # ④ clarify 分支（ADR-001-5：clarify 后也发 done）
            if decision.need_clarify:
                yield _sse(
                    "meta",
                    {
                        "conversation_id": conversation_id,
                        "msg_id": assistant_msg_id,
                        "skill": skill_id,
                        "confidence": confidence,
                        "provider": "system",
                    },
                )
                yield _sse(
                    "clarify",
                    {
                        "question": decision.clarify_question,
                        "options": decision.clarify_options,
                    },
                )
                yield _sse(
                    "done",
                    {
                        "usage": {"tokens_in": 0, "tokens_out": 0},
                        "latency_ms": int((time.monotonic() - t_start) * 1000),
                    },
                )
                return

            # SSE: meta（业务事件永远第一个）
            yield _sse(
                "meta",
                {
                    "conversation_id": conversation_id,
                    "msg_id": assistant_msg_id,
                    "skill": skill_id,
                    "confidence": confidence,
                    "provider": intended_provider,
                },
            )

            # ⑤ 构建 SkillContext + 获取 skill 实例
            skill_ctx = SkillContext(
                user_id=user_id,
                user_role=active_role,
                conversation_id=conversation_id,
                request_id=request_id,
                db=db,
                llm=model_router,
                rag=get_rag_pipeline(),
                memory=get_memory_manager(),
                context_assembler=get_context_assembler(),
            )

            registry = get_skill_registry()
            skill = registry.get(skill_id)
            if skill is None:
                skill = registry.get("chat")  # 兜底
            if skill is None:
                # 注册表为空（lifespan 未执行或注册失败）——如实报错，不崩溃
                log.error("chat.skill_registry_empty", skill_id=skill_id)
                yield _sse(
                    "error",
                    {
                        "code": 50301,
                        "message": "技能服务未就绪，请稍后重试",
                        "recoverable": True,
                    },
                )
                return

            # ⑥ 执行 skill（带心跳：10s 无事件发 ": ping"）
            params = decision.params or {"question": user_message}
            if "question" not in params:
                params["question"] = user_message

            stream_iter = skill.run(params, skill_ctx).__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(
                        stream_iter.__anext__(), timeout=SSE_HEARTBEAT_SECONDS
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    yield ": ping\n\n"
                    continue

                evt_type = event.get("type", "")

                if evt_type == "_result_meta":
                    result_meta = event.get("data", {})
                    provider_name = result_meta.get("provider", provider_name)
                    full_text = result_meta.get("full_text", full_text)
                    continue

                if evt_type == "error":
                    error_occurred = True
                    yield _sse("error", event["data"])
                    break

                if evt_type == "status":
                    yield _sse("status", event["data"])
                    continue

                if evt_type == "token":
                    # 边转发边累积——CancelledError 时部分回答落库依赖此值
                    full_text += event["data"].get("text", "")
                    yield _sse("token", event["data"])
                    continue

            if not error_occurred:
                latency_ms = int((time.monotonic() - t_start) * 1000)
                interrupted = bool(result_meta.get("interrupted"))

                # ⑦ guard.check_output
                citations = skill_ctx.get_citations()
                valid_ids = [c["chunk_id"] for c in citations] if citations else None
                full_text = await guard.check_output(
                    full_text, {"user_id": user_id},
                    valid_chunk_ids=valid_ids,
                    degraded=bool(result_meta.get("degraded")),
                )

                # citation 事件（主链路统一发）
                if citations:
                    yield _sse("citation", {"items": citations})

                # badge 事件
                badge_level = ""
                if result_meta.get("degraded"):
                    badge_level = "L3-模型"
                elif citations:
                    badge_level = "L2-知识库"
                if badge_level:
                    yield _sse("badge", {"level": badge_level})

                # done 事件的 usage：providers 透传的真实值（缺失时降级估算）
                usage = result_meta.get("usage") or {}
                tokens_in = usage.get("prompt_tokens") or _est_tokens(user_message)
                tokens_out = usage.get("completion_tokens") or _est_tokens(full_text)

                # ⑧ 信封落库（含 usage/badge，供幂等重放完整还原）
                blocks = [{"type": "markdown", "content": full_text}]
                if result_meta.get("notice"):
                    blocks.append({"type": "notice", "content": result_meta["notice"]})
                if citations:
                    blocks.append({"type": "citation", "items": citations})

                envelope = {
                    "msg_id": assistant_msg_id,
                    "role": "assistant",
                    "blocks": blocks,
                    "meta": {
                        "skill": skill_id,
                        "confidence": confidence,
                        "provider": provider_name,
                        "latency_ms": latency_ms,
                        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        "ai_generated": True,
                    },
                }
                if badge_level:
                    envelope["meta"]["badge"] = badge_level
                if interrupted:
                    envelope["meta"]["interrupted"] = True

                assistant_msg = Message(
                    conversation_id=conversation_id,
                    client_msg_id=ai_client_msg_id,
                    role="assistant",
                    content=full_text,
                    envelope=envelope,
                    skill_id=skill_id,
                    route_info={"confidence": confidence, "intent": skill_id},
                )
                db.add(assistant_msg)

                # 更新会话消息计数
                await db.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(message_count=Conversation.message_count + 1)
                )

                # skill_runs 落库
                skill_run = SkillRun(
                    skill_id=skill_id,
                    user_id=user_id,
                    params=params,
                    status="success",
                    latency_ms=latency_ms,
                )
                db.add(skill_run)
                await db.flush()
                # 关键：done 之前显式提交——客户端收到 done 即可能重试/进入次轮，
                # 必须保证彼时幂等重放与会话查找能命中已提交数据
                await db.commit()

                # done 事件（正常路径永远最后）
                yield _sse(
                    "done",
                    {
                        "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out},
                        "latency_ms": latency_ms,
                    },
                )

                # ⑨ 异步后台任务：滚动摘要 + 首轮标题生成
                background_tasks.add_task(_bg_summary, conversation_id, request_id)
                if title_is_default:
                    background_tasks.add_task(_bg_title, conversation_id, user_message, request_id)

                log.info(
                    "chat.done",
                    skill=skill_id,
                    provider=provider_name,
                    latency_ms=latency_ms,
                    interrupted=interrupted,
                )

        except asyncio.CancelledError:
            # 客户端断连：部分回答落库（标记中断），便于幂等重放还原现场。
            # 用独立任务执行——当前生成器正被取消，直接 await 会被二次取消打断
            log.info("chat.stream.cancelled", partial_chars=len(full_text))
            if full_text:
                _spawn_partial_persist(
                    conversation_id,
                    ai_client_msg_id,
                    assistant_msg_id,
                    skill_id,
                    confidence,
                    provider_name,
                    full_text,
                    request_id,
                )
            raise

        except Exception:
            log.exception("chat.stream.error")
            if full_text:
                await _persist_partial(
                    conversation_id,
                    ai_client_msg_id,
                    assistant_msg_id,
                    skill_id,
                    confidence,
                    provider_name,
                    full_text,
                    request_id,
                )
            if not error_occurred:
                yield _sse(
                    "error",
                    {
                        "code": 50001,
                        "message": "服务繁忙，请稍后重试",
                        "recoverable": True,
                    },
                )

    return StreamingResponse(
        _cleanup_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Request-Id": request_id,
        },
    )


# ========== 后台任务 ==========


async def _bg_summary(conversation_id: str, request_id: str) -> None:
    """滚动摘要触发（新 session，失败只记日志）"""
    try:
        async with async_session_factory() as session:
            await get_memory_manager().maybe_update_summary(conversation_id, session, request_id)
    except Exception as e:
        logger.warning("bg.summary_failed", error=str(e)[:200], request_id=request_id)


async def _bg_title(conversation_id: str, user_message: str, request_id: str) -> None:
    """首轮对话 AI 标题生成（新 session，失败只记日志）"""
    try:
        router = get_model_router()
        result = await router.chat(
            [{"role": "user", "content": TITLE_PROMPT.format(message=user_message[:500])}],
            temperature=0.3,
            max_tokens=40,
            request_id=request_id,
            scene="title",
        )
        title = result["content"].strip().strip("\"'《》<>\n ")[:15]
        if not title:
            return
        async with async_session_factory() as session:
            # 只在标题仍是默认值时覆盖（避免覆盖用户手动改名）
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.title == "新对话")
                .values(title=title)
            )
            await session.commit()
        logger.info("bg.title_generated", conversation_id=conversation_id, title=title)
    except Exception as e:
        logger.warning("bg.title_failed", error=str(e)[:200], request_id=request_id)


def _spawn_partial_persist(*args) -> None:
    """在独立任务中执行 _persist_partial（断连场景，失败只记日志）"""

    async def _run() -> None:
        await _persist_partial(*args)

    try:
        task = asyncio.create_task(_run())
        task.add_done_callback(_swallow_task_error)
    except RuntimeError:
        # 无运行中事件循环——放弃落库
        pass


def _swallow_task_error(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("chat.partial_persist_task_error", error=str(exc)[:200])


async def _persist_partial(
    conversation_id: str,
    ai_client_msg_id: str,
    assistant_msg_id: str,
    skill_id: str,
    confidence: float,
    provider_name: str,
    full_text: str,
    request_id: str,
) -> None:
    """中断/异常时部分回答落库（新 session，meta.interrupted=True）"""
    try:
        async with async_session_factory() as session:
            envelope = {
                "msg_id": assistant_msg_id,
                "role": "assistant",
                "blocks": [
                    {"type": "markdown", "content": full_text},
                    {"type": "notice", "content": "回答中断，内容可能不完整"},
                ],
                "meta": {
                    "skill": skill_id,
                    "confidence": confidence,
                    "provider": provider_name,
                    "interrupted": True,
                    "ai_generated": True,
                },
            }
            session.add(
                Message(
                    conversation_id=conversation_id,
                    client_msg_id=ai_client_msg_id,
                    role="assistant",
                    content=full_text,
                    envelope=envelope,
                    skill_id=skill_id,
                    route_info={"confidence": confidence, "intent": skill_id},
                )
            )
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(message_count=Conversation.message_count + 1)
            )
            await session.commit()
        logger.info("chat.partial_persisted", request_id=request_id, chars=len(full_text))
    except Exception as e:
        logger.warning("chat.partial_persist_failed", error=str(e)[:200], request_id=request_id)


# ========== 会话管理端点 ==========


@router.get("/conversations")
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["sub"]
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    )
    conversations = result.scalars().all()
    count_result = await db.execute(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
    )
    total = count_result.scalar() or 0
    items = [
        {
            "id": str(c.id),
            "title": c.title,
            "activeRole": c.active_role,
            "summary": c.summary,
            "messageCount": c.message_count,
            "createdAt": c.created_at.isoformat() if c.created_at else None,
            "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]
    return ApiResponse(code=0, message="ok", data={"items": items, "total": total})


@router.post("/conversations")
async def create_conversation(
    body: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["sub"]
    conv = Conversation(user_id=user_id, active_role=body.workspace, title="新对话")
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


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    limit: int = 20,
    before: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["sub"]
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if result.scalar_one_or_none() is None:
        return ApiResponse(code=40401, message="会话不存在")

    query = (
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
        .order_by(Message.created_at.desc())
        .limit(limit + 1)
    )
    if before:
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


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user["sub"]
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
    conv.deleted_at = datetime.now(UTC)
    await db.flush()
    return ApiResponse(code=0, message="ok", data=None)


@router.post("/feedback")
async def submit_feedback(
    body: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """回答有问题上报"""
    from app.models.event import Event

    event = Event(
        user_id=current_user["sub"],
        event="feedback",
        props={"target_msg_id": body.target_msg_id, "reason": body.reason},
    )
    db.add(event)
    await db.flush()
    return ApiResponse(code=0, message="ok", data=None)


# ========== 工具函数 ==========


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _replay_response(msg: Message, request_id: str):
    """幂等重放：按落库信封完整还原 meta → token → citation → badge → done"""
    envelope = msg.envelope or {}
    env_meta = envelope.get("meta", {})

    async def replay_stream():
        yield ": open\n\n"
        yield _sse(
            "meta",
            {
                "conversation_id": str(msg.conversation_id),
                "msg_id": envelope.get("msg_id", str(msg.id)),
                "skill": env_meta.get("skill", msg.skill_id or "chat"),
                "confidence": env_meta.get("confidence", 1.0),
                "provider": env_meta.get("provider", "deepseek"),
            },
        )

        blocks = envelope.get("blocks") or []
        if blocks:
            for block in blocks:
                btype = block.get("type")
                if btype == "markdown":
                    yield _sse("token", {"text": block.get("content", "")})
                elif btype == "citation":
                    yield _sse("citation", {"items": block.get("items", [])})
        elif msg.content:
            # 旧数据无信封：保底回放正文
            yield _sse("token", {"text": msg.content})

        if env_meta.get("badge"):
            yield _sse("badge", {"level": env_meta["badge"]})

        usage = env_meta.get("usage") or {"tokens_in": 0, "tokens_out": 0}
        yield _sse(
            "done",
            {
                "usage": usage,
                "latency_ms": env_meta.get("latency_ms", 0),
            },
        )

    return StreamingResponse(
        replay_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Request-Id": request_id,
            "X-Idempotent-Replay": "true",
        },
    )


def _sse_error_response(code: int, message: str, request_id: str):
    async def error_stream():
        yield ": open\n\n"
        yield _sse("error", {"code": code, "message": message, "recoverable": False})

    return StreamingResponse(
        error_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Request-Id": request_id},
    )


def _age_seconds(dt: datetime) -> float:
    """计算距现在秒数（兼容 naive/aware 时间戳）"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds()


def _est_tokens(text: str) -> int:
    return max(1, int(len(text) / 2.5))


def _release_sse_slot(user_id: str) -> None:
    """释放 SSE 并发槽位（信号量 + per-user 计数器），用于 chat() 提前返回的路径"""
    _global_sse_semaphore.release()
    count = _user_sse_counts.get(user_id, 1) - 1
    if count <= 0:
        _user_sse_counts.pop(user_id, None)
    else:
        _user_sse_counts[user_id] = count
    logger.debug(
        "chat.sse.slot_released_early",
        user_id=user_id,
        global_remaining=_global_sse_semaphore._value,
    )
