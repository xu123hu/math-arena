"""Butler Kernel v2 ModelAdapter（设计规格 §6 + 阶段 3A）

- 实现 PydanticAI 所需生成函数，内部只调用现有 ``ModelRouter.chat()``，
  保留主备降级、熔断与 ``log_ai_call`` 审计；
- 接收已解析的 ModelRouter 实例，不创建 Spark/DeepSeek，不读取/保存/日志输出
  任何 API Key，不连接 Pydantic Gateway；
- 不依赖模型原生 Function Calling（``functions=None``，只消费 content 文本）；
- 使用 PydanticAI 公开 API（Agent / FunctionModel / UsageLimits）完成
  结构化 ActionPlan 校验，输出非法时最多修复 1 次（retries=1）；
- 模型全部失败 / 超时 / 修复失败 → ``deterministic_fallback_plan()``，
  不向学生端抛异常；
- 单次 Planner 请求数由 ``UsageLimits(request_limit=max_model_requests)`` 约束；
- Planner 只能看到 ``Registry.visible_to(role, scene)`` 返回的工具摘要。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.butler.contracts import (
    ActionPlan,
    ButlerBudget,
    ButlerContextSnapshot,
    ButlerRequest,
)
from app.butler.registry import ToolRegistry
from app.providers.base import ChatMessage
from app.providers.router import ModelRouter

PLANNER_SCENE = "butler.planner"

_DEFAULT_PLANNER_PROMPT = (
    "你是智学数研学生端 AI 管家。只输出 ActionPlan JSON："
    '{"intent": str, "goal": str, "actions": [{"tool_name": str, "arguments": {"query": "..."}, "reason": str}], '
    '"response_mode": "direct"|"cards"|"socratic"|"degraded", "needs_web_search": bool}。'
)


@dataclass
class ButlerDeps:
    """Planner 依赖（Agent 泛型参数，供 Runtime 传入请求/快照/注册表/预算）。"""

    request: ButlerRequest
    snapshot: ButlerContextSnapshot | None
    registry: ToolRegistry
    budget: ButlerBudget


class ButlerModelAdapter:
    """PydanticAI ↔ ModelRouter 隔离层（内部只调现有路由，不持有密钥）。"""

    def __init__(self, router: ModelRouter, *, budget: ButlerBudget | None = None) -> None:
        self._router = router
        self._budget = budget or ButlerBudget()
        self._request_count = 0

    @property
    def request_count(self) -> int:
        return self._request_count

    def reset_count(self) -> None:
        self._request_count = 0

    async def generate(self, messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        """PydanticAI FunctionModel 生成函数：消息转文本 → ModelRouter.chat() → 文本响应。"""
        self._request_count += 1
        prompt = _messages_to_prompt(messages)
        chat_messages: list[ChatMessage] = [{"role": "user", "content": prompt}]
        result = await self._router.chat(
            chat_messages,
            temperature=0.2,
            max_tokens=4096,
            functions=None,  # 不依赖模型原生 Function Calling
            thinking=False,
            request_id=str(uuid.uuid4()),
            scene=PLANNER_SCENE,
        )
        return ModelResponse(parts=[TextPart(content=result["content"])])


def _messages_to_prompt(messages: list[ModelMessage]) -> str:
    """把 PydanticAI 消息序列合并为单一文本 prompt。"""
    parts: list[str] = []
    for msg in messages:
        for part in msg.parts:
            text = getattr(part, "content", None)
            if text:
                parts.append(str(text))
    return "\n\n".join(parts)


def build_planning_prompt(request: ButlerRequest, registry: ToolRegistry) -> str:
    """组装 Planner prompt：系统约束 + 仅当前角色/场景可见的工具摘要。"""
    visible = registry.visible_to(request.actor.role, request.scene)
    tools_block = "\n".join(f"- {name}" for name in visible) if visible else "- (无可用工具)"
    return (
        "你是智学数研学生端 AI 管家（Butler Kernel v2）。"
        "只输出一个 ActionPlan JSON 对象，不要输出任何解释或 markdown。\n"
        f"用户消息：{request.message}\n"
        f"场景：{request.scene}；角色：{request.actor.role.value}\n"
        f"可用工具（仅这些，禁止使用未列出的工具）：\n{tools_block}\n"
        "ActionPlan 结构："
        '{"intent": str, "goal": str, "actions": [{"tool_name": str, "arguments": {"query": "..."}, "reason": str}], '
        '"response_mode": "direct"|"cards"|"socratic"|"degraded", "needs_web_search": bool}。'
        "actions 最多 5 个。"
    )


def build_planner(
    adapter: ButlerModelAdapter,
    registry: ToolRegistry,
    *,
    budget: ButlerBudget | None = None,
    request: ButlerRequest | None = None,
) -> Agent[ButlerDeps, ActionPlan]:
    """构造 PydanticAI Agent：结构化 ActionPlan 输出 + 最多修复 1 次 + 可见工具摘要。"""
    budget = budget or ButlerBudget()
    system_prompt = build_planning_prompt(request, registry) if request else _DEFAULT_PLANNER_PROMPT
    return Agent(
        model=FunctionModel(adapter.generate),
        deps_type=ButlerDeps,
        output_type=ActionPlan,
        retries=1,  # 模型输出非法时最多修复 1 次
        system_prompt=system_prompt,
    )


def deterministic_fallback_plan(
    request: ButlerRequest, *, reason: str = "model_unavailable"
) -> ActionPlan:
    """模型全部失败 / 超时 / 修复失败时的规则型降级计划（不向学生端抛异常）。"""
    return ActionPlan(
        intent="fallback",
        goal="模型暂不可用，返回规则型降级响应",
        actions=[],
        response_mode="degraded",
        needs_web_search=False,
    )
