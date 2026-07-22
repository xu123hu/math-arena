"""上下文装配（kernel/context.py）

总预算 12K token，P0~P2 保命段永不裁。裁剪顺序：P3→P5→P4→P6。
M0 简化：仅 P0(system) + P1(history) + P2(user message)。
"""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message

logger = structlog.get_logger()

# M0 数学教师 system prompt
SYSTEM_PROMPT = (
    "你是一位专业的数学教师助手，名叫 MathArena。你的职责是：\n"
    "1. 帮助学生理解数学概念，解答数学问题\n"
    "2. 用清晰、循序渐进的方式讲解解题思路\n"
    "3. 鼓励学生独立思考，适时给予提示而非直接给出答案\n"
    "4. 支持高等数学、线性代数、概率统计、离散数学等大学数学领域\n"
    "5. 回答时使用 Markdown 格式，数学公式使用 LaTeX 语法（行内 $...$，块级 $$...$$）\n\n"
    "请始终使用中文回答，保持友善和专业的语气。"
)

# 粗略 token 估算
CHARS_PER_TOKEN = 2

# M0 上下文预算 12K tokens
TOTAL_BUDGET_TOKENS = 12_000
SYSTEM_RESERVED_TOKENS = 800
USER_MSG_RESERVED_TOKENS = 2000
HISTORY_BUDGET_TOKENS = TOTAL_BUDGET_TOKENS - SYSTEM_RESERVED_TOKENS - USER_MSG_RESERVED_TOKENS


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数"""
    return len(text) // CHARS_PER_TOKEN + 1


class ContextAssembler:
    """上下文装配器"""

    BUDGET = {
        "P0_system_persona": 800,
        "P1_user_message": 2000,
        "P2_skill_params": 600,
        "P3_rag_chunks": 4000,
        "P4_working_memory": 1600,
        "P5_user_profile": 500,
        "P6_episodic": 800,
        "P7_output_spec": 400,
    }

    async def assemble(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_message: str,
    ) -> list[dict]:
        """装配上下文消息列表。

        M0 简化版：system prompt + 历史消息 + 当前用户消息。
        """
        messages: list[dict] = []

        # P0: system prompt
        messages.append({"role": "system", "content": SYSTEM_PROMPT})

        # P1: 加载历史消息
        history = await self._load_history(db, conversation_id)
        history_budget_chars = HISTORY_BUDGET_TOKENS * CHARS_PER_TOKEN

        # 从最新往前累加，直到超出预算
        selected: list[dict] = []
        total_chars = 0
        for msg in reversed(history):
            msg_chars = len(msg["content"])
            if total_chars + msg_chars > history_budget_chars:
                break
            selected.append(msg)
            total_chars += msg_chars

        selected.reverse()
        messages.extend(selected)

        # P2: 当前用户消息
        messages.append({"role": "user", "content": user_message})

        token_est = sum(_estimate_tokens(m["content"]) for m in messages)
        logger.info(
            "context.assembled",
            history_count=len(selected),
            total_messages=len(messages),
            estimated_tokens=token_est,
        )

        return messages

    async def _load_history(self, db: AsyncSession, conversation_id: str) -> list[dict]:
        """从 messages 表加载会话历史（最近 50 条）"""
        result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.created_at.desc())
            .limit(50)
        )
        rows = result.scalars().all()
        rows = list(reversed(rows))

        history: list[dict] = []
        for msg in rows:
            if msg.role in ("user", "assistant"):
                history.append(
                    {
                        "role": msg.role,
                        "content": msg.content or "",
                    }
                )
        return history
