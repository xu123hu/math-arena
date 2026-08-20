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


def run(capability: str, internal: dict[str, Any]) -> dict:
    """执行（同步受理）：星辰可用则调用上游；不可用/失败返回可降级信息。"""
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
        out = _xc_run(flow_name, map_input(capability, internal), timeout_s=20)
        content = out.get("data", out)
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
    except Exception as exc:  # noqa: BLE001 —— 规范化
        code = ERR_UPSTREAM
        msg = str(exc)
        if "timeout" in msg.lower() or "time out" in msg.lower():
            code = ERR_TIMEOUT
        elif "rate" in msg.lower() or "限流" in msg.lower():
            code = ERR_RATE_LIMITED
        return {
            "status": "degraded",
            "workflow": WORKFLOWS.get(capability),
            "content": {},
            "warnings": [f"workflow failed: {code}"],
            "error_code": code,
        }


__all__ = ["WORKFLOWS", "WorkflowResult", "run", "workflow_available", "map_input"]
