"""Butler Kernel v2 类型化工具注册表（设计规格 §7 + 阶段 2 Task 4）

- 每个工具声明：唯一名称、版本、描述、输入模型、输出模型、风险级别、
  角色集合、场景集合、默认超时、幂等策略与 handler；
- 重复名称拒绝；未知工具返回稳定错误（不携带堆栈/内部类名）；
- 输入/输出分别由 input_model / output_model 校验；
- F14（wf_verify_derivation / research.verify_derivation / Lean 工具）通过
  M2_DENIED_TOOLS 名单在注册层直接拒绝，无法进入 Registry；
- 本阶段不注册真实领域工具，仅提供类型化注册与校验；
- 不使用 eval / getattr 动态反射查找业务函数：handler 由 Executor 在
  后续阶段按工具名显式调用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.butler.contracts import ActorRole, ToolRisk

#: F14 / M2 范围外工具：注册层直接拒绝（PolicyGate 另持有一份做调用期兜底）。
M2_DENIED_TOOLS = frozenset(
    {
        "research.verify_derivation",
        "wf_verify_derivation",
        "lean.verify",
        "lean.prove",
        "lean.check",
    }
)


class ToolRegistryError(Exception):
    """注册表稳定错误基类（message 对外可见，不得含堆栈/密钥）。"""


class DuplicateToolError(ToolRegistryError):
    """工具名重复注册。"""


class UnknownToolError(ToolRegistryError):
    """工具名未注册。"""


class ToolForbiddenError(ToolRegistryError):
    """工具名命中 M2_DENIED_TOOLS / 注册层拒绝名单。"""


class ToolDefinition(BaseModel):
    """一个工具的完整声明（类型化 I/O + 权限 + 风险 + handler）。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    risk: ToolRisk
    allowed_roles: frozenset[ActorRole]
    allowed_scenes: frozenset[str]
    timeout_s: float = 20.0
    idempotency_required: bool = False
    handler: Callable[..., Awaitable[Any]]


class ToolRegistry:
    """显式 allowlist 工具注册表（进程内单例由 Runtime 持有）。"""

    def __init__(self, denied_tools: frozenset[str] = M2_DENIED_TOOLS) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._denied_tools = denied_tools

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._denied_tools:
            raise ToolForbiddenError(f"tool is denied: {definition.name}")
        if definition.name in self._tools:
            raise DuplicateToolError(f"tool already registered: {definition.name}")
        self._tools[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise UnknownToolError(f"unknown tool: {name}")
        return tool

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def visible_to(self, role: ActorRole, scene: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                name
                for name, tool in self._tools.items()
                if role in tool.allowed_roles and scene in tool.allowed_scenes
            )
        )

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 input_model 校验并规范化参数；ValidationError 原样上抛由 Policy 捕获。"""
        tool = self.get(name)
        validated = tool.input_model.model_validate(arguments)
        return validated.model_dump()

    def validate_output(self, name: str, data: Any) -> Any:
        """按 output_model 校验工具输出。"""
        tool = self.get(name)
        validated = tool.output_model.model_validate(data)
        return validated.model_dump()
