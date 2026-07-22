"""聊天技能（skills/chat.py）

M0 简化版：纯对话，不接 RAG/记忆。
从 kernel context 获取组装好的 messages，调用 ModelRouter.chat_stream() 流式生成。
"""

from collections.abc import AsyncIterator
import time

import structlog

from app.providers.base import ChatMessage
from app.providers.router import get_model_router
from app.skills.base import SkillExecutor

logger = structlog.get_logger()


class ChatSkill(SkillExecutor):
    """聊天兜底技能"""

    manifest = {
        "id": "chat",
        "name": "自由对话",
        "description": "通用数学对话，不依赖外部知识库",
        "triggers": ["default"],
    }

    async def run(self, params: dict, ctx: dict) -> AsyncIterator[dict]:
        """执行聊天技能，yield SSE 事件。

        params: {"messages": list[ChatMessage], "request_id": str}
        ctx: {"user_id": str, "conversation_id": str, ...}
        """
        messages: list[ChatMessage] = params["messages"]
        request_id: str = params["request_id"]

        router = get_model_router()
        t0 = time.monotonic()
        full_text = ""
        provider_name = "deepseek"  # 默认，实际由 router 决定

        try:
            async for token in router.chat_stream(
                messages,
                temperature=0.3,
                max_tokens=2048,
                request_id=request_id,
                scene="chat",
            ):
                full_text += token
                yield {"type": "token", "data": {"text": token}}

            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info("chat.skill.done", request_id=request_id, latency_ms=latency_ms)

            # 返回元信息供主链路使用
            yield {
                "type": "_result_meta",
                "data": {
                    "full_text": full_text,
                    "provider": provider_name,
                    "latency_ms": latency_ms,
                },
            }

        except Exception as e:
            logger.exception("chat.skill.error", request_id=request_id)
            yield {
                "type": "error",
                "data": {"code": 50001, "message": str(e), "recoverable": False},
            }
