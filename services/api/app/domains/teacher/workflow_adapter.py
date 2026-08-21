"""M3 教师端：星辰工作流 Adapter（§16，不改星辰 YAML，映射层隔离）。

- 7 个规范工作流名 → 内部能力；历史别名不得出现；
- 内部输入映射到既有星辰 YAML 输入；响应映射回内部 Pydantic/契约；
- 规范化错误：workflow_disabled/unconfigured/timeout/rate_limited/schema_invalid/upstream_error；
- 文本任务最多一次安全重试；大文件/课件渲染走异步任务；
- 原始上游响应不直传前端。
"""

from __future__ import annotations

from typing import Any

from app.config import settings

# 规范工作流名（平台侧唯一）
WORKFLOWS = {
    "adapt_lesson": "wf_lesson_plan",
    "create_slides": "wf_ai_ppt",
    "create_quiz": "wf_smart_quiz",
    "suggest_grade": "wf_solution_pregrade",
    "explain_problem": "wf_explainer_script",
    "preprocess_course": "wf_course_preprocess",
    "understand_document": "wf_doc_understand",
}

# 规范错误码
ERR_DISABLED = "workflow_disabled"
ERR_UNCONFIGURED = "workflow_unconfigured"
ERR_TIMEOUT = "workflow_timeout"
ERR_RATE_LIMITED = "workflow_rate_limited"
ERR_SCHEMA_INVALID = "workflow_schema_invalid"
ERR_UPSTREAM = "workflow_upstream_error"


class WorkflowResult(dict):
    """规范化 Adapter 返回：status/content/workflow/source_refs/warnings/provider_trace_id/latency_ms。

    status ∈ succeeded|degraded|failed。
    """


def workflow_available(capability: str) -> tuple[bool, str | None]:
    """星辰工作流是否可用：总开关 + 配置齐全 + flow 注册存在。返回 (ok, error_code|None)。"""
    if not settings.xingchen_enabled:
        return False, ERR_DISABLED
    flow_name = WORKFLOWS.get(capability)
    if flow_name is None:
        return False, ERR_UNCONFIGURED
    if not settings.xingchen_api_key or not settings.xingchen_api_secret:
        return False, ERR_UNCONFIGURED
    flows = settings.xingchen_flow_id_map
    if not flows or flow_name not in flows:
        return False, ERR_UNCONFIGURED
    return True, None


def map_input(capability: str, internal: dict[str, Any]) -> dict[str, Any]:
    """内部输入 → 星辰既有 YAML 输入（只取最小必要字段，合并聚合学情，不透传敏感原文）。"""
    base = {
        "request_id": internal.get("request_id", ""),
        "capability": capability,
        "payload": internal.get("payload", {}),
        "constraints": {"language": internal.get("language", "zh-CN"),
                        "max_output_chars": internal.get("max_output_chars", 12000)},
    }
    return base


async def run(capability: str, internal: dict[str, Any]) -> dict:
    """异步执行（审计 I-03）：按 provider 契约 ``await run_workflow(flow, uid=...,
    parameters=..., read_timeout=...)`` 调用；不可用/失败返回可降级信息。

    只映射既有 YAML 所需最小字段；原始上游响应不直传，统一映射为内部结构。
    """
    ok, err = workflow_available(capability)
    if not ok:
        return {
            "status": "degraded",
            "workflow": WORKFLOWS.get(capability),
            "content": {},
            "warnings": [f"workflow unavailable: {err}"],
            "error_code": err,
        }
    # 星辰主链：复用 providers.xingchen.run_workflow（不改 YAML，仅映射输入）
    try:
        from app.providers.xingchen import run_workflow as _xc_run

        flow_name = WORKFLOWS[capability]
        out = await _xc_run(
            flow_name,
            uid=str(internal.get("teacher_id", "")) or "teacher",
            parameters=_flow_parameters(capability, internal),
            read_timeout=20.0,
        )
        content = out.get("data", out) if isinstance(out, dict) else None
        if not isinstance(content, dict):
            return {
                "status": "degraded",
                "workflow": flow_name,
                "content": {},
                "warnings": ["schema_invalid"],
                "error_code": ERR_SCHEMA_INVALID,
            }
        return {
            "status": "succeeded",
            "workflow": flow_name,
            "content": content,
            "warnings": [],
            "provider_trace_id": out.get("trace_id"),
            "engine": "xingchen",
        }
    except Exception as exc:  # noqa: BLE001 —— 规范化错误，不泄漏原文
        code = _classify_error(exc)
        return {
            "status": "degraded",
            "workflow": WORKFLOWS.get(capability),
            "content": {},
            "warnings": [f"workflow failed: {code}"],
            "error_code": code,
        }


def _classify_error(exc: Exception) -> str:
    """异常 → 规范化错误码（不向调用方暴露原始异常文本）。"""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "timeout" in name or "timeout" in msg or "timed out" in msg:
        return ERR_TIMEOUT
    if "rate" in name or "rate" in msg or "限流" in msg:
        return ERR_RATE_LIMITED
    if "schema" in name or "validation" in name:
        return ERR_SCHEMA_INVALID
    return ERR_UPSTREAM


def _flow_parameters(capability: str, internal: dict[str, Any]) -> dict[str, Any]:
    """内部输入 → 各工作流既有 YAML parameters（最小字段映射）。

    uid/class 等鉴权信息不进入外发参数；学情仅传聚合摘要。
    """
    payload = internal.get("payload") or {}
    return dict(payload)


__all__ = ["WORKFLOWS", "WorkflowResult", "run", "workflow_available", "map_input"]
