"""Butler Kernel v2 PolicyGate（阶段 2 Task 4）

覆盖 10 步固定校验顺序与全部稳定错误码：
- 未知工具 / 角色越权 / 场景越权 / 参数非法 / 预算超限 / 幂等缺失 /
  外部未授权 / 搜索未确认 / M2 范围外；
- 学生不能规划教师/科研/管理工具；
- 搜索三态：显式开启 / 本地拒答 / 均无；
- 错误响应不泄漏内部异常（无 ValidationError / Traceback）。
"""

import uuid
from typing import Any

import pytest
from pydantic import BaseModel

from app.butler.contracts import (
    ActionPlan,
    ActorContext,
    ActorRole,
    ButlerBudget,
    ButlerRequest,
    PlannedAction,
    ToolRisk,
)
from app.butler.policy import (
    ERROR_BUDGET_EXCEEDED,
    ERROR_CONFIRMATION_REQUIRED,
    ERROR_EXTERNAL_NOT_ALLOWED,
    ERROR_IDEMPOTENCY_REQUIRED,
    ERROR_INVALID_ARGUMENTS,
    ERROR_M2_OUT_OF_SCOPE,
    ERROR_RISK_DENIED,
    ERROR_ROLE_DENIED,
    ERROR_SCENE_DENIED,
    ERROR_UNKNOWN_TOOL,
    M2_DENIED_TOOLS,
    PolicyDecision,
    PolicyGate,
)
from app.butler.registry import ToolDefinition, ToolRegistry


class EchoInput(BaseModel):
    query: str
    limit: int = 3


class EchoOutput(BaseModel):
    answer: str


async def _echo_handler(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"answer": arguments.get("query", "")}


def _tool(
    name: str,
    *,
    roles: frozenset[ActorRole],
    scenes: frozenset[str],
    risk: ToolRisk = ToolRisk.READ,
    idempotency_required: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="1.0.0",
        description="policy test tool",
        input_model=EchoInput,
        output_model=EchoOutput,
        risk=risk,
        allowed_roles=roles,
        allowed_scenes=scenes,
        idempotency_required=idempotency_required,
        handler=_echo_handler,
    )


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        _tool(
            "student.read",
            roles=frozenset({ActorRole.STUDENT}),
            scenes=frozenset({"student.dashboard"}),
        )
    )
    reg.register(
        _tool(
            "teacher.grade.read",
            roles=frozenset({ActorRole.TEACHER}),
            scenes=frozenset({"teacher.dashboard"}),
        )
    )
    reg.register(
        _tool(
            "research.analyze",
            roles=frozenset({ActorRole.RESEARCHER}),
            scenes=frozenset({"research.dashboard"}),
        )
    )
    reg.register(
        _tool(
            "admin.config.write",
            roles=frozenset({ActorRole.ADMIN}),
            scenes=frozenset({"admin.model"}),
            risk=ToolRisk.WRITE,
            idempotency_required=True,
        )
    )
    reg.register(
        _tool(
            "test.write",
            roles=frozenset({ActorRole.STUDENT}),
            scenes=frozenset({"student.dashboard"}),
            risk=ToolRisk.WRITE,
        )
    )
    reg.register(
        _tool(
            "test.external",
            roles=frozenset({ActorRole.STUDENT}),
            scenes=frozenset({"student.dashboard"}),
            risk=ToolRisk.EXTERNAL,
        )
    )
    return reg


@pytest.fixture
def policy(registry: ToolRegistry) -> PolicyGate:
    return PolicyGate(registry)


@pytest.fixture
def student_request() -> ButlerRequest:
    return ButlerRequest(
        actor=ActorContext(user_id=uuid.uuid4(), role=ActorRole.STUDENT),
        message="今天复习什么",
        scene="student.dashboard",
        client_request_id="crid-1",
    )


def _plan(*tool_names: str, needs_web_search: bool = False) -> ActionPlan:
    return ActionPlan(
        intent="review",
        goal="复习",
        actions=[
            PlannedAction(tool_name=t, arguments={"query": "x"}, reason="test")
            for t in tool_names
        ],
        response_mode="cards",
        needs_web_search=needs_web_search,
    )


# ---------- 校验顺序：1 工具注册 ----------


def test_unknown_tool_rejected(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_action(student_request, PlannedAction(tool_name="no.such", reason="x"))
    assert d.allowed is False
    assert d.error_code == ERROR_UNKNOWN_TOOL


def test_unknown_tool_error_message_is_stable(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_action(student_request, PlannedAction(tool_name="no.such", reason="x"))
    assert "Traceback" not in d.message
    assert "ValidationError" not in d.message


# ---------- 校验顺序：2 角色 ----------


@pytest.mark.parametrize(
    "tool_name",
    ["teacher.grade.read", "research.analyze", "admin.config.write"],
)
def test_student_cannot_plan_teacher_research_admin_tools(
    policy: PolicyGate, student_request: ButlerRequest, tool_name: str
):
    d = policy.validate_plan(student_request, _plan(tool_name))
    assert d.allowed is False
    assert d.error_code == ERROR_ROLE_DENIED


# ---------- 校验顺序：3 场景 ----------


def test_scene_mismatch_rejected(policy: PolicyGate, student_request: ButlerRequest):
    # student.read 只允许 student.dashboard；换成不匹配场景
    request = student_request.model_copy(update={"scene": "teacher.dashboard"})
    d = policy.validate_action(request, PlannedAction(tool_name="student.read", reason="x"))
    assert d.allowed is False
    assert d.error_code == ERROR_SCENE_DENIED


# ---------- 校验顺序：4 参数 ----------


def test_invalid_arguments_rejected(policy: PolicyGate, student_request: ButlerRequest):
    plan = ActionPlan(
        intent="review",
        goal="复习",
        actions=[PlannedAction(tool_name="student.read", arguments={"query": 123}, reason="x")],
        response_mode="direct",
    )
    d = policy.validate_plan(student_request, plan)
    assert d.allowed is False
    assert d.error_code == ERROR_INVALID_ARGUMENTS
    # 不泄漏 pydantic 内部类名/堆栈
    assert "ValidationError" not in d.message
    assert "Traceback" not in d.message


# ---------- 校验顺序：5 预算 ----------


def test_plan_over_budget_rejected(policy: PolicyGate, student_request: ButlerRequest):
    plan = _plan(*["student.read"] * 5)
    d = policy.validate_plan(student_request, plan, budget=ButlerBudget(max_tool_calls=3))
    assert d.allowed is False
    assert d.error_code == ERROR_BUDGET_EXCEEDED


def test_plan_within_budget_allowed(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_plan(student_request, _plan("student.read"), budget=ButlerBudget())
    assert d.allowed is True


# ---------- 校验顺序：6 风险等级 ----------


def test_risk_not_allowed_rejected(registry: ToolRegistry, student_request: ButlerRequest):
    gate = PolicyGate(registry, allowed_risks=frozenset({ToolRisk.READ}))
    d = gate.validate_action(
        student_request,
        PlannedAction(tool_name="test.write", arguments={"query": "x"}, reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_RISK_DENIED


# ---------- 校验顺序：7 WRITE 幂等 ----------


def test_write_without_idempotency_rejected(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_action(
        student_request,
        PlannedAction(tool_name="test.write", arguments={"query": "x"}, reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_IDEMPOTENCY_REQUIRED


def test_write_with_idempotency_allowed(policy: PolicyGate, student_request: ButlerRequest):
    plan = _plan("admin.config.write")
    # 管理员场景
    request = student_request.model_copy(
        update={
            "actor": ActorContext(
                user_id=uuid.uuid4(), role=ActorRole.ADMIN, locale="zh-CN"
            ),
            "scene": "admin.model",
        }
    )
    d = policy.validate_plan(request, plan)
    assert d.allowed is True


# ---------- 校验顺序：8 EXTERNAL ----------


def test_external_not_authorized_rejected(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_action(
        student_request,
        PlannedAction(tool_name="test.external", arguments={"query": "x"}, reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_EXTERNAL_NOT_ALLOWED


def test_external_authorized_allowed(policy: PolicyGate, student_request: ButlerRequest):
    d = policy.validate_action(
        student_request,
        PlannedAction(tool_name="test.external", arguments={"query": "x"}, reason="x"),
        external_allowed=True,
    )
    assert d.allowed is True


# ---------- 校验顺序：9 联网搜索 ----------


def test_web_search_requires_opt_in_or_refusal(policy: PolicyGate):
    assert policy.allow_web_search(enabled_by_user=True, local_refused=False) is True
    assert policy.allow_web_search(enabled_by_user=False, local_refused=True) is True
    assert policy.allow_web_search(enabled_by_user=False, local_refused=False) is False


def test_plan_needs_web_search_without_opt_in_rejected(
    policy: PolicyGate, student_request: ButlerRequest
):
    d = policy.validate_plan(
        student_request, _plan("student.read", needs_web_search=True)
    )
    assert d.allowed is False
    assert d.error_code == ERROR_CONFIRMATION_REQUIRED


def test_plan_needs_web_search_with_opt_in_allowed(
    policy: PolicyGate, student_request: ButlerRequest
):
    d = policy.validate_plan(
        student_request,
        _plan("student.read", needs_web_search=True),
        web_search_enabled=True,
    )
    assert d.allowed is True


def test_plan_needs_web_search_with_local_refusal_allowed(
    policy: PolicyGate, student_request: ButlerRequest
):
    d = policy.validate_plan(
        student_request,
        _plan("student.read", needs_web_search=True),
        web_search_local_refused=True,
    )
    assert d.allowed is True


# ---------- 校验顺序：10 M2 范围排除 ----------


def test_m2_denied_tools_constant_covers_f14():
    assert "research.verify_derivation" in M2_DENIED_TOOLS
    assert "wf_verify_derivation" in M2_DENIED_TOOLS
    assert any(n.startswith("lean.") for n in M2_DENIED_TOOLS)


def test_policy_rejects_registered_m2_tool():
    """PolicyGate 兜底：即使工具绕过注册层进入 Registry，调用仍被拒绝。"""
    reg = ToolRegistry()
    reg._tools["wf_verify_derivation"] = _tool(
        "wf_verify_derivation",
        roles=frozenset({ActorRole.STUDENT}),
        scenes=frozenset({"student.dashboard"}),
    )
    gate = PolicyGate(reg)
    request = ButlerRequest(
        actor=ActorContext(user_id=uuid.uuid4(), role=ActorRole.STUDENT),
        message="x",
        scene="student.dashboard",
        client_request_id="crid-1",
    )
    d = gate.validate_action(
        request,
        PlannedAction(tool_name="wf_verify_derivation", arguments={"query": "x"}, reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_M2_OUT_OF_SCOPE


def test_unregistered_f14_tool_rejected_as_unknown(
    policy: PolicyGate, student_request: ButlerRequest
):
    d = policy.validate_action(
        student_request,
        PlannedAction(tool_name="research.verify_derivation", reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_UNKNOWN_TOOL


# ---------- 阶段 2.1：搜索 Action 按实际工具名授权 ----------


def _search_registry_and_gate() -> tuple[ToolRegistry, PolicyGate]:
    reg = ToolRegistry()
    reg.register(
        _tool(
            "xingchen.web_search",
            roles=frozenset({ActorRole.STUDENT}),
            scenes=frozenset({"student.dashboard"}),
            risk=ToolRisk.EXTERNAL,
        )
    )
    return reg, PolicyGate(reg)


def test_web_search_tools_constant_covers_xingchen():
    from app.butler.policy import WEB_SEARCH_TOOLS

    assert "xingchen.web_search" in WEB_SEARCH_TOOLS


def test_web_search_action_rejected_even_if_plan_flag_false(
    student_request: ButlerRequest,
):
    """needs_web_search=false 且 external_allowed=true 时，搜索 Action 仍被拒。"""
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_plan(
        student_request,
        _plan("xingchen.web_search"),  # needs_web_search 默认 False
        external_allowed=True,
    )
    assert d.allowed is False
    assert d.error_code == ERROR_CONFIRMATION_REQUIRED


def test_external_denied_precedes_web_search_confirmation(
    student_request: ButlerRequest,
):
    """EXTERNAL 场景未授权先返回 external_not_allowed。"""
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_plan(student_request, _plan("xingchen.web_search"))
    assert d.allowed is False
    assert d.error_code == ERROR_EXTERNAL_NOT_ALLOWED


def test_web_search_action_authorized_then_confirmation(
    student_request: ButlerRequest,
):
    """EXTERNAL 已授权但搜索未确认 → confirmation_required。"""
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_plan(
        student_request, _plan("xingchen.web_search"), external_allowed=True
    )
    assert d.allowed is False
    assert d.error_code == ERROR_CONFIRMATION_REQUIRED


def test_validate_action_web_search_default_safe_deny(
    student_request: ButlerRequest,
):
    """validate_action 单独调用搜索工具时默认安全拒绝。"""
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_action(
        student_request,
        PlannedAction(tool_name="xingchen.web_search", arguments={"query": "x"}, reason="x"),
        external_allowed=True,
    )
    assert d.allowed is False
    assert d.error_code == ERROR_CONFIRMATION_REQUIRED


def test_validate_action_web_search_allowed_with_opt_in(
    student_request: ButlerRequest,
):
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_action(
        student_request,
        PlannedAction(tool_name="xingchen.web_search", arguments={"query": "x"}, reason="x"),
        external_allowed=True,
        web_search_enabled=True,
    )
    assert d.allowed is True


def test_validate_action_web_search_allowed_with_local_refusal(
    student_request: ButlerRequest,
):
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_action(
        student_request,
        PlannedAction(tool_name="xingchen.web_search", arguments={"query": "x"}, reason="x"),
        external_allowed=True,
        web_search_local_refused=True,
    )
    assert d.allowed is True


def test_validate_plan_passes_web_search_state_to_actions(
    student_request: ButlerRequest,
):
    """validate_plan 把真实搜索状态传给每个 Action。"""
    _reg, gate = _search_registry_and_gate()
    d = gate.validate_plan(
        student_request,
        _plan("xingchen.web_search"),
        external_allowed=True,
        web_search_enabled=True,
    )
    assert d.allowed is True


def test_any_web_search_suffix_tool_checked(student_request: ButlerRequest):
    """任意 *.web_search 工具都按搜索授权检查（不限于显式名单）。"""
    reg = ToolRegistry()
    reg.register(
        _tool(
            "custom.vendor.web_search",
            roles=frozenset({ActorRole.STUDENT}),
            scenes=frozenset({"student.dashboard"}),
            risk=ToolRisk.EXTERNAL,
        )
    )
    gate = PolicyGate(reg)
    d = gate.validate_action(
        student_request,
        PlannedAction(tool_name="custom.vendor.web_search", arguments={"query": "x"}, reason="x"),
        external_allowed=True,
    )
    assert d.allowed is False
    assert d.error_code == ERROR_CONFIRMATION_REQUIRED


# ---------- 阶段 2.1：lean.* 前缀 Policy 兜底 ----------


def test_policy_rejects_lean_prefix_even_if_registered():
    """即使绕过注册层塞入 lean.custom，Policy 仍返回 m2_out_of_scope。"""
    reg = ToolRegistry()
    reg._tools["lean.custom"] = _tool(
        "lean.custom",
        roles=frozenset({ActorRole.STUDENT}),
        scenes=frozenset({"student.dashboard"}),
    )
    gate = PolicyGate(reg)
    request = ButlerRequest(
        actor=ActorContext(user_id=uuid.uuid4(), role=ActorRole.STUDENT),
        message="x",
        scene="student.dashboard",
        client_request_id="crid-1",
    )
    d = gate.validate_action(
        request,
        PlannedAction(tool_name="lean.custom", arguments={"query": "x"}, reason="x"),
    )
    assert d.allowed is False
    assert d.error_code == ERROR_M2_OUT_OF_SCOPE


def test_non_lean_tool_plan_allowed(policy: PolicyGate, student_request: ButlerRequest):
    """非 Lean 普通工具不受 lean.* 拦截影响。"""
    d = policy.validate_plan(student_request, _plan("student.read"))
    assert d.allowed is True


# ---------- 决策模型 ----------


def test_policy_decision_model():
    d = PolicyDecision(allowed=True)
    assert d.error_code is None
    assert d.message == ""
