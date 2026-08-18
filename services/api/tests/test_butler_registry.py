"""Butler Kernel v2 类型化工具注册表（阶段 2 Task 4）

覆盖：
- register / get / names / visible_to / validate_arguments / validate_output；
- 重复名称拒绝、未知工具稳定错误；
- 输入/输出分别由 input_model / output_model 校验；
- F14（research.verify_derivation / wf_verify_derivation / lean.*）注册被拒；
- 空 tool_name 拒绝。

本阶段只注册测试工具，不注册真实领域工具。
"""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.butler.contracts import ActorRole, ToolRisk
from app.butler.registry import (
    DuplicateToolError,
    ToolDefinition,
    ToolForbiddenError,
    ToolRegistry,
    UnknownToolError,
)


class EchoInput(BaseModel):
    query: str
    limit: int = 3


class EchoOutput(BaseModel):
    answer: str


async def _echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"answer": arguments.get("query", "")}


def _def(name: str = "test.echo", **overrides: Any) -> ToolDefinition:
    values: dict[str, Any] = {
        "name": name,
        "version": "1.0.0",
        "description": "test tool",
        "input_model": EchoInput,
        "output_model": EchoOutput,
        "risk": ToolRisk.READ,
        "allowed_roles": frozenset({ActorRole.STUDENT, ActorRole.TEACHER}),
        "allowed_scenes": frozenset({"student.dashboard", "student.practice"}),
        "handler": _echo_handler,
    }
    values.update(overrides)
    return ToolDefinition(**values)


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_def())
    return reg


# ---------- 注册与查询 ----------


def test_register_and_get():
    reg = _registry()
    got = reg.get("test.echo")
    assert got.name == "test.echo"
    assert got.risk == ToolRisk.READ


def test_names_returns_registered_names():
    reg = _registry()
    assert "test.echo" in reg.names()
    assert "research.verify_derivation" not in reg.names()


def test_duplicate_name_rejected():
    reg = _registry()
    with pytest.raises(DuplicateToolError):
        reg.register(_def())


def test_unknown_tool_raises_stable_error():
    reg = _registry()
    with pytest.raises(UnknownToolError) as exc:
        reg.get("no.such.tool")
    assert "no.such.tool" in str(exc.value)
    # 稳定错误：不携带堆栈/内部类名
    assert "Traceback" not in str(exc.value)


def test_empty_tool_name_rejected():
    with pytest.raises(ValidationError):
        _def(name="")


# ---------- visible_to ----------


def test_visible_to_filters_by_role_and_scene():
    reg = _registry()
    visible = reg.visible_to(ActorRole.STUDENT, "student.dashboard")
    assert "test.echo" in visible
    # 角色不在 allowed_roles
    assert "test.echo" not in reg.visible_to(ActorRole.ADMIN, "student.dashboard")
    # 场景不在 allowed_scenes
    assert "test.echo" not in reg.visible_to(ActorRole.STUDENT, "admin.model")


# ---------- 参数/输出校验 ----------


def test_validate_arguments_coerces_and_returns():
    reg = _registry()
    out = reg.validate_arguments("test.echo", {"query": "hi", "limit": "5"})
    assert out == {"query": "hi", "limit": 5}


def test_validate_arguments_type_error_rejected():
    reg = _registry()
    with pytest.raises(ValidationError):
        reg.validate_arguments("test.echo", {"query": 123})


def test_validate_arguments_unknown_tool():
    reg = _registry()
    with pytest.raises(UnknownToolError):
        reg.validate_arguments("missing.tool", {})


def test_validate_output_ok():
    reg = _registry()
    assert reg.validate_output("test.echo", {"answer": "hi"}) == {"answer": "hi"}


def test_validate_output_wrong_shape_rejected():
    reg = _registry()
    with pytest.raises(ValidationError):
        reg.validate_output("test.echo", {"not_answer": 1})


# ---------- F14 护栏 ----------


@pytest.mark.parametrize(
    "denied_name",
    ["research.verify_derivation", "wf_verify_derivation", "lean.verify", "lean.prove"],
)
def test_register_rejects_m2_denied_name(denied_name: str):
    reg = ToolRegistry()
    with pytest.raises(ToolForbiddenError):
        reg.register(_def(name=denied_name))


def test_m2_registry_has_no_f14():
    reg = _registry()
    for f14 in ("research.verify_derivation", "wf_verify_derivation"):
        assert f14 not in reg.names()


def test_denied_tools_can_be_relaxed_for_policy_testing():
    """Policy 兜底测试需要"已注册但属 M2 名单"的工具，注册层可显式放宽。"""
    reg = ToolRegistry(denied_tools=frozenset())
    reg.register(_def(name="wf_verify_derivation"))
    assert "wf_verify_derivation" in reg.names()
