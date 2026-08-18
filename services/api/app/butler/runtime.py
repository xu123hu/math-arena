"""Butler Kernel v2 ButlerRuntime（设计规格 §5 + 阶段 3C）

固定管线：Context → Plan → Policy → Execute → Compose，每阶段记录 AgentStep。

- 模型失败 / 超时 / 修复失败 → deterministic fallback（degraded），不向学生端抛异常；
- Policy 拒绝 → 拒绝 envelope（不静默越权）；
- 重复 client_request_id（账本唯一约束）→ duplicate envelope，不重复执行；
- 模型请求数受 UsageLimits(request_limit=max_model_requests) 约束，工具调用 ≤5；
- Shadow 模式 WRITE/EXTERNAL 一律 shadow_skipped；
- 账本只存脱敏摘要（digest），不存密钥/完整文本/思维链。
"""

from __future__ import annotations

import asyncio
import time
import uuid

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.butler.composer import ResultComposer
from app.butler.context import ContextAssembler, context_assembler
from app.butler.contracts import (
    ActionPlan,
    ActorContext,
    ActorRole,
    ButlerBudget,
    ButlerContextSnapshot,
    ButlerEnvelope,
    ButlerRequest,
    ToolResult,
)
from app.butler.executor import ButlerExecutor, _digest
from app.butler.model_adapter import (
    ButlerDeps,
    ButlerModelAdapter,
    build_planning_prompt,
    deterministic_fallback_plan,
)
from app.butler.policy import PolicyGate
from app.butler.registry import ToolRegistry
from app.models.agent_run import AgentRun, AgentStep, ToolInvocation
from app.models.database import background_session_factory

STAGES = ("context", "plan", "policy", "execute", "compose")


class ButlerRuntime:
    """统一入口：组装上下文 → 计划 → 校验 → 执行 → 组合，并完整记账。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy: PolicyGate,
        assembler: ContextAssembler | None = None,
        adapter: ButlerModelAdapter | None = None,
        planner: Agent | None = None,
        executor: ButlerExecutor | None = None,
        composer: ResultComposer | None = None,
        budget: ButlerBudget | None = None,
        shadow: bool = False,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._assembler = assembler or context_assembler
        self.adapter = adapter
        self._planner = planner
        self._executor = executor
        self._composer = composer or ResultComposer()
        self._budget = budget or ButlerBudget()
        self._shadow = shadow

    async def run(self, request: ButlerRequest, db: AsyncSession) -> ButlerEnvelope:
        run_id = uuid.uuid4()
        started = time.perf_counter()
        run_row = AgentRun(
            user_id=request.actor.user_id,
            role=request.actor.role.value,
            scene=request.scene,
            client_request_id=request.client_request_id,
            intent="",
            status="running",
        )
        db.add(run_row)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            return self._duplicate_envelope(request)

        # ---- 1. Context ----
        snapshot, ctx_error = await self._run_stage(
            "context", self._assembler.build(request, db)
        )

        # ---- 2. Plan ----
        plan, plan_error = await self._run_stage("plan", self._plan(request, snapshot))

        # ---- 3. Policy ----
        decision = self._policy.validate_plan(request, plan)
        policy_error = None if decision.allowed else decision.error_code

        # ---- 4. Execute ----
        results, exec_error = await self._run_stage(
            "execute",
            self._executor.execute_plan(
                run_id,
                request,
                plan,
                db,
                shadow=self._shadow,
                budget=self._budget,
            ),
        )

        # ---- 5. Compose ----
        degraded = (
            plan.response_mode == "degraded"
            or not decision.allowed
            or any(not r.ok for r in results)
        )
        envelope = self._composer.compose(
            run_id=run_id,
            request=request,
            plan=plan,
            results=results,
            degraded=degraded,
        )

        # ---- 记账 ----
        latency_ms = int((time.perf_counter() - started) * 1000)
        run_row.intent = plan.intent
        run_row.status = "fallback" if plan.response_mode == "degraded" else "succeeded"
        run_row.degraded = degraded
        run_row.model_request_count = self.adapter.request_count if self.adapter else 0
        run_row.tool_call_count = len(results)
        run_row.finished_at = _now()
        run_row.latency_ms = latency_ms
        run_row.error_code = decision.error_code if not decision.allowed else (exec_error or policy_error)

        for seq, stage in enumerate(STAGES):
            stage_meta = {"context": ctx_error, "plan": plan_error, "policy": policy_error, "execute": exec_error, "compose": None}[stage]
            db.add(
                AgentStep(
                    run_id=run_row.id,
                    sequence=seq,
                    stage=stage,
                    status="ok" if stage_meta is None else "failed",
                    error_code=stage_meta,
                )
            )

        for action, result in zip(plan.actions, results, strict=False):
            db.add(
                ToolInvocation(
                    run_id=run_row.id,
                    tool_name=action.tool_name,
                    tool_version=self._tool_version(action.tool_name),
                    status=_invocation_status(result),
                    latency_ms=0,
                    idempotency_key=_invocation_idem_key(result),
                    arguments_digest=_digest(action.arguments),
                    result_digest=_digest(result.data) if result.ok else None,
                    error_code=result.error_code,
                )
            )

        await db.flush()
        return envelope

    def _tool_version(self, tool_name: str) -> str:
        try:
            return self._registry.get(tool_name).version
        except Exception:  # noqa: BLE001 —— 未注册工具（policy 已拦）不打断记账
            return ""

    async def _plan(
        self, request: ButlerRequest, snapshot: ButlerContextSnapshot
    ) -> ActionPlan:
        if self._planner is None or self.adapter is None:
            return deterministic_fallback_plan(request, reason="no_planner")
        prompt = build_planning_prompt(request, self._registry)
        deps = ButlerDeps(
            request=request, snapshot=snapshot, registry=self._registry, budget=self._budget
        )
        try:
            async with asyncio.timeout(self._budget.timeout_s):
                result = await self._planner.run(
                    prompt,
                    deps=deps,
                    usage_limits=UsageLimits(
                        request_limit=self._budget.max_model_requests
                    ),
                )
            return result.output
        except Exception:  # noqa: BLE001 —— 模型全失败/超时 → 规则降级
            return deterministic_fallback_plan(request, reason="planner_failed")

    async def _run_stage(self, stage: str, coro):
        try:
            value = await coro
            return value, None
        except Exception:  # noqa: BLE001
            return None, f"{stage}_error"

    def _duplicate_envelope(self, request: ButlerRequest) -> ButlerEnvelope:
        return ButlerEnvelope(
            run_id=uuid.uuid4(),
            intent="",
            text="重复请求已忽略",
            blocks=[],
            actions=[],
            sources=[],
            degraded=True,
            trace={"error_code": "duplicate_request"},
        )


def _invocation_status(result: ToolResult) -> str:
    if result.error_code == "shadow_skipped":
        return "shadow_skipped"
    return "ok" if result.ok else "failed"


def _invocation_idem_key(result: ToolResult) -> str | None:
    # ToolResult 不携带幂等键；写工具重放由 Executor 内部保证，账本记录摘要即可
    return None


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def build_shadow_runtime() -> ButlerRuntime:
    """无副作用影子运行实例：空 Registry → fallback 计划 → 无动作。"""
    registry = ToolRegistry()
    policy = PolicyGate(registry)
    executor = ButlerExecutor(registry, policy, budget=ButlerBudget())
    return ButlerRuntime(
        registry=registry,
        policy=policy,
        executor=executor,
        budget=ButlerBudget(),
        shadow=True,
    )


async def run_v2_shadow(user_id: uuid.UUID, scene: str, message: str) -> None:
    """独立后台 session 的 v2 影子运行（best-effort，异常吞掉；无业务副作用）。"""
    try:
        async with background_session_factory() as db:
            runtime = build_shadow_runtime()
            req = ButlerRequest(
                actor=ActorContext(user_id=user_id, role=ActorRole.STUDENT),
                message=message,
                scene=scene,
                client_request_id=f"shadow-{uuid.uuid4().hex[:16]}",
            )
            await runtime.run(req, db)
            await db.commit()
    except Exception:  # noqa: BLE001 —— 影子运行绝不影响主链路
        pass
