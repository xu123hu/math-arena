"""意图路由（kernel/router.py）

三路信号合并：L0 前置信号 → L2 Function Calling → L3 置信度闸门。
禁止任何形式的硬编码关键词表（手册 §7.2）。
"""

import json
import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill
from app.providers.router import get_model_router

logger = structlog.get_logger()

# L0 slash 命令映射（结构性信号，非关键词路由）
# 注：/出题（quiz）为 M2 功能，届时恢复
SLASH_COMMANDS: dict[str, str] = {
    "/qa": "qa_rag",
    "/答疑": "qa_rag",
    "/chat": "chat",
}

# L3 置信度阈值
CONFIDENCE_HIGH = 0.75
CONFIDENCE_LOW = 0.40


@dataclass
class RouteDecision:
    """路由决策结果"""

    skill_id: str  # 命中的 skill，"chat" 为兜底
    confidence: float  # 0~1
    params: dict = field(default_factory=dict)  # Function Calling 抽出的参数
    need_clarify: bool = False  # True 时主链路转澄清分支
    clarify_question: str = ""
    clarify_options: list[str] = field(default_factory=list)


class IntentRouter:
    """意图路由器：L0 + L2 + L3 三路信号合并"""

    async def route(
        self,
        message: str,
        *,
        db: AsyncSession,
        user_id: str,
        surface: str = "",
        request_id: str = "",
    ) -> RouteDecision:
        """意图路由主函数

        三路信号按优先级合并：
        1. L0 前置信号（<5ms）：slash 命令、surface 上下文
        2. L2 Function Calling：skills manifest → functions 声明
        3. L3 置信度闸门：≥0.75 直接执行，0.4~0.75 低置信，<0.4 澄清
        """
        log = logger.bind(request_id=request_id, user_id=user_id)
        t0 = time.monotonic()

        # ===== L0 前置信号（<5ms，不调模型）=====
        l0_result = self._check_l0(message, surface)
        if l0_result is not None:
            log.info("router.l0_hit", skill_id=l0_result.skill_id)
            return l0_result

        # ===== L2 Function Calling =====
        active_skills = await self._get_active_skills(db)
        if active_skills:
            l2_result = await self._function_calling_route(
                message, active_skills, request_id=request_id
            )
            if l2_result is not None:
                # ===== L3 置信度闸门 =====
                decision = self._apply_confidence_gate(l2_result, message)
                latency = int((time.monotonic() - t0) * 1000)
                log.info(
                    "router.decided",
                    skill_id=decision.skill_id,
                    confidence=decision.confidence,
                    need_clarify=decision.need_clarify,
                    latency_ms=latency,
                )
                return decision

        # 兜底：chat
        log.info("router.fallback_chat")
        return RouteDecision(
            skill_id="chat",
            confidence=0.5,
            params={"question": message},
            need_clarify=False,
        )

    def _check_l0(self, message: str, surface: str) -> RouteDecision | None:
        """L0 前置信号：slash 命令 + surface 上下文（结构性信号）"""
        # Slash 命令匹配
        for cmd, skill_id in SLASH_COMMANDS.items():
            if message.startswith(cmd):
                remaining = message[len(cmd) :].strip()
                return RouteDecision(
                    skill_id=skill_id,
                    confidence=0.99,
                    params={"question": remaining or message},
                    need_clarify=False,
                )
        return None

    async def _get_active_skills(self, db: AsyncSession) -> list[dict]:
        """从 skills 表获取所有 active 状态的 skill manifest"""
        result = await db.execute(select(Skill).where(Skill.status == "active"))
        skills = result.scalars().all()
        return [
            {
                "id": s.id,
                "name": s.name,
                "manifest": s.manifest if isinstance(s.manifest, dict) else {},
            }
            for s in skills
            if s.id != "chat"  # chat 是兜底，不参与 Function Calling
        ]

    async def _function_calling_route(
        self,
        message: str,
        active_skills: list[dict],
        *,
        request_id: str,
    ) -> RouteDecision | None:
        """L2: 使用 LLM Function Calling 进行意图识别"""
        if not active_skills:
            return None

        # 构建 functions 声明（从 skill manifest 压缩）
        functions = []
        for skill in active_skills:
            manifest = skill["manifest"]
            desc = manifest.get("description", skill["name"])
            params_schema = manifest.get(
                "params_schema",
                {
                    "type": "object",
                    "properties": {"question": {"type": "string", "description": "用户问题原文"}},
                    "required": ["question"],
                },
            )
            functions.append(
                {
                    "name": skill["id"],
                    "description": desc,
                    "parameters": params_schema,
                }
            )

        # 调用 LLM Function Calling
        router = get_model_router()
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个意图路由器。根据用户消息选择最匹配的工具函数。"
                    "如果没有明确匹配，选择最接近的函数并设置较低的置信度。"
                    "用户消息可能包含数学问题、知识查询、闲聊等。"
                ),
            },
            {"role": "user", "content": message},
        ]

        try:
            result = await router.chat(
                messages,
                temperature=0.0,
                max_tokens=256,
                functions=functions,
                request_id=request_id,
                scene="router",
            )

            # 解析 Function Calling 响应
            active_ids = {s["id"] for s in active_skills}
            return self._parse_fc_response(result, message, active_ids)

        except Exception as e:
            logger.warning("router.fc_failed", error=str(e)[:200])
            # Function Calling 失败时返回 None，走兜底
            return None

    def _parse_fc_response(
        self, result: dict, original_message: str, active_ids: set[str]
    ) -> RouteDecision | None:
        """解析 Function Calling 响应

        优先读结构化 tool_calls（providers 层已解析），
        content-JSON 作为兜底；skill_id 不在 active 列表视为未命中。
        """
        # 1. 结构化 tool_calls（首选路径）
        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            skill_id = call.get("name", "")
            params = call.get("arguments", {})
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = {}
            if skill_id in active_ids:
                return RouteDecision(
                    skill_id=skill_id,
                    confidence=0.85,
                    params=params if params else {"question": original_message},
                    need_clarify=False,
                )
            # 模型 hallucinate 了不存在的函数 → 未命中
            logger.warning("router.fc_unknown_skill", skill_id=skill_id)
            return None

        # 2. content-JSON 兜底（部分模型把调用结果写在 content 里）
        content = result.get("content", "")
        try:
            if isinstance(content, str) and content.strip().startswith("{"):
                data = json.loads(content)
                if "name" in data:
                    skill_id = data["name"]
                    if skill_id not in active_ids:
                        return None
                    params = data.get("arguments", {})
                    if isinstance(params, str):
                        params = json.loads(params)
                    confidence = data.get("confidence", 0.8)
                    return RouteDecision(
                        skill_id=skill_id,
                        confidence=float(confidence),
                        params=params if params else {"question": original_message},
                        need_clarify=False,
                    )
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

        # 无法解析为结构化结果 → 未命中，走 chat 兜底
        return None

    def _apply_confidence_gate(self, decision: RouteDecision, message: str) -> RouteDecision:
        """L3 置信度闸门

        >= 0.75: 直接执行
        0.40 ~ 0.75: 低置信执行（标注）
        < 0.40: 触发澄清
        """
        if decision.confidence >= CONFIDENCE_HIGH:
            return decision

        if decision.confidence >= CONFIDENCE_LOW:
            # 低置信但仍执行，前端可显示"猜你想用 XX"
            return decision

        # 低于阈值，触发澄清
        clarify_q = f"我理解你可能想问关于「{message[:30]}」的问题，请问你具体想要？"
        return RouteDecision(
            skill_id=decision.skill_id,
            confidence=decision.confidence,
            params=decision.params,
            need_clarify=True,
            clarify_question=clarify_q,
            clarify_options=[
                "解释这个数学概念",
                "帮我解这道题",
                "只是随便聊聊",
            ],
        )


# ---- 全局单例 ----
_intent_router: IntentRouter | None = None


def get_intent_router() -> IntentRouter:
    """获取全局 IntentRouter 单例"""
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router


async def route(
    message: str,
    *,
    db: AsyncSession,
    user_id: str,
    surface: str = "",
    request_id: str = "",
) -> RouteDecision:
    """便捷路由函数（兼容旧接口）"""
    router = get_intent_router()
    return await router.route(
        message, db=db, user_id=user_id, surface=surface, request_id=request_id
    )
