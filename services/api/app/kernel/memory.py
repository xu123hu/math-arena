"""记忆管理（kernel/memory.py）

工作记忆 = 滚动摘要 + 最近 10 条消息。
每 8 条消息触发摘要更新（BackgroundTasks 异步，失败只记日志）。
M1 阶段 user_profiles 只读（M2 才事件驱动写）。
"""

from dataclasses import dataclass, field

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user_profile import UserProfile as UserProfileModel
from app.providers.router import get_model_router

logger = structlog.get_logger()

# 摘要触发阈值：每 8 条消息（4 轮对话）
SUMMARY_TRIGGER_COUNT = 8
# 最近消息窗口
RECENT_MESSAGES_LIMIT = 12
# 摘要最大长度
SUMMARY_MAX_CHARS = 300

SUMMARY_PROMPT = r"""你是一个数学对话摘要压缩器。请将以下对话历史压缩为不超过300字的摘要。

要求：
1. 保留讨论过的题目、核心概念和关键定义
2. 保留学生卡住的点和未完成的追问
3. 保留重要的结论、公式和推导结果（保留 LaTeX 格式）
4. 保留对话中引入的数学符号和变量名（如 f(x)、Δ 等）
5. 保留解题思路和方法名称（如"用换元法"、"反证法"）
6. 用第三人称描述（"用户询问了..."、"AI 解释了..."）
7. 数学公式保留 LaTeX 格式，行内用 \(...\)，独立公式用 $$...$$

已有摘要：
{existing_summary}

新增对话：
{new_messages}

请输出压缩后的摘要（不超过300字）："""


@dataclass
class WorkingMemory:
    """工作记忆"""

    summary: str = ""
    recent_messages: list[dict] = field(default_factory=list)


@dataclass
class UserProfileData:
    """用户档案数据（M1 只读，M2 事件驱动写）"""

    grade: str = ""
    level: str = "unknown"
    weak_points: list[dict] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)


class MemoryManager:
    """记忆管理器"""

    async def get_working_memory(self, conversation_id: str, db: AsyncSession) -> WorkingMemory:
        """返回 {summary, recent_messages}：滚动摘要 + 最近 10 条原文。"""
        # 获取会话摘要
        conv_result = await db.execute(
            select(Conversation.summary).where(Conversation.id == conversation_id)
        )
        summary = conv_result.scalar() or ""

        # 获取最近 10 条消息
        msg_result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
                Message.role.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at.desc())
            .limit(RECENT_MESSAGES_LIMIT)
        )
        rows = msg_result.scalars().all()
        rows = list(reversed(rows))  # 时间正序

        recent_messages = [{"role": msg.role, "content": msg.content or ""} for msg in rows]

        return WorkingMemory(summary=summary, recent_messages=recent_messages)

    async def maybe_update_summary(
        self, conversation_id: str, db: AsyncSession, request_id: str = ""
    ) -> bool:
        """每 8 条消息触发一次摘要更新。

        异步执行（由 BackgroundTasks 调用），失败只记日志不重试。
        返回是否执行了更新。
        """
        log = logger.bind(request_id=request_id, conversation_id=conversation_id)

        try:
            # 检查消息计数
            conv_result = await db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv is None:
                return False

            # 只在消息数为 8 的倍数时触发
            if conv.message_count == 0 or conv.message_count % SUMMARY_TRIGGER_COUNT != 0:
                return False

            log.info("memory.summary_trigger", message_count=conv.message_count)

            # 获取现有摘要
            existing_summary = conv.summary or ""

            # 获取最近 12 条消息用于压缩
            msg_result = await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.deleted_at.is_(None),
                    Message.role.in_(["user", "assistant"]),
                )
                .order_by(Message.created_at.desc())
                .limit(SUMMARY_TRIGGER_COUNT)
            )
            rows = msg_result.scalars().all()
            rows = list(reversed(rows))

            new_messages_text = "\n".join(
                f"{'用户' if m.role == 'user' else 'AI'}: {(m.content or '')[:200]}" for m in rows
            )

            # 调用 LLM 压缩摘要
            router = get_model_router()
            prompt = SUMMARY_PROMPT.format(
                existing_summary=existing_summary or "（无）",
                new_messages=new_messages_text,
            )

            result = await router.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
                request_id=request_id,
                scene="summary",
            )

            new_summary = result["content"][: SUMMARY_MAX_CHARS * 2]  # 安全截断

            # 写回 conversations.summary
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(summary=new_summary)
            )
            await db.commit()

            log.info("memory.summary_updated", summary_len=len(new_summary))
            return True

        except Exception as e:
            log.warning("memory.summary_failed", error=str(e)[:200])
            return False

    async def get_user_profile(self, user_id: str, db: AsyncSession) -> UserProfileData:
        """获取用户档案。M1 只读不写。"""
        result = await db.execute(
            select(UserProfileModel).where(UserProfileModel.user_id == user_id)
        )
        profile = result.scalar_one_or_none()

        if profile is None:
            return UserProfileData()

        return UserProfileData(
            grade=profile.grade or "",
            level=profile.level or "unknown",
            weak_points=profile.weak_points if isinstance(profile.weak_points, list) else [],
            preferences=profile.preferences if isinstance(profile.preferences, dict) else {},
        )

    async def get_message_count(self, conversation_id: str, db: AsyncSession) -> int:
        """获取会话消息数"""
        result = await db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar() or 0


# ---- 全局单例 ----
_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """获取全局 MemoryManager 单例"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
