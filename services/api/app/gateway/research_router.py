"""科研端试点路由（SSOT §4.6 / API 文档 §8.3：wf_verify_derivation 最终落地）

POST /api/research/derivations/verify — 推导验证试点
- 星辰优先：run_workflow("wf_verify_derivation")（输出模型 VerifyDerivationOut）
- 本地降级：LLM 生成 SymPy 验证代码 → 沙箱执行 → verdict 判定（consistent/inconsistent/unverifiable）
- 双挂 → 50301（契约口径：无本地备用时"验证服务暂不可用"）

M2 试点边界：student 端不开放（SSOT §1.2 Out of Scope），仅 teacher/researcher。
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.gateway.auth import require_role
from app.models.database import get_db
from app.providers.sandbox import run_sandbox

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

_VERDICTS = ("consistent", "inconsistent", "unverifiable")

_VERIFY_CODE_PROMPT = """你是数学推导验证助手。把用户的推导过程转换为可独立执行的 Python/SymPy 验证代码。

要求：
1. 代码必须能独立运行（完整 import sympy），末行必须输出一行判定结果：`print("VERIFIED")` 或 `print("REJECTED")`（根据推导每一步与最终结论是否数学上成立）。
2. 若推导内容无法程序化验证（非数学/信息不足/表述模糊），输出 `print("UNVERIFIABLE")`。
3. 只输出代码，不要任何解释、注释以外的多余文本。
4. 代码中禁止访问网络、读取文件、执行 shell；仅允许 sympy/math 等纯计算库。

用户推导：
{derivation}

{expected_hint}
"""


class DerivationVerifyRequest(BaseModel):
    derivation_text: str = Field(..., max_length=8000, description="自然语言+LaTeX 推导")
    domain_hint: str | None = Field(
        default=None, pattern="^(probability|modeling|algebra|general)$", description="首选概率/中学数学建模"
    )
    expected_result: str | None = Field(default=None, description="声明的结论公式 LaTeX")


def _normalize_verdict(raw: str) -> str:
    v = (raw or "unverifiable").strip().lower()
    return v if v in _VERDICTS else "unverifiable"


async def _generate_verify_code(llm, req: DerivationVerifyRequest, request_id: str) -> str | None:
    """本地降级：LLM 生成验证代码"""
    from app.providers.base import ChatMessage

    expected_hint = (
        f"声明的最终结论：{req.expected_result}（用于比对，代码应验证推导是否推出该结论）"
        if req.expected_result
        else "未声明最终结论，验证推导内部每一步的数学正确性即可。"
    )
    messages: list[ChatMessage] = [
        {"role": "system", "content": "你只输出可执行的 Python 代码。"},
        {
            "role": "user",
            "content": _VERIFY_CODE_PROMPT.format(
                derivation=req.derivation_text[:6000], expected_hint=expected_hint
            ),
        },
    ]
    try:
        result = await llm.chat(
            messages,
            temperature=0.2,
            max_tokens=4000,
            request_id=request_id,
            scene="verify_derivation",
        )
        return (result.get("content") or "").strip()
    except Exception as e:
        logger.warning("verify_derivation.codegen_failed", error=str(e)[:150])
        return None


def _judge_local(code: str, result: dict, expected_result: str | None) -> tuple[str, str]:
    """本地判定：沙箱执行结果 → verdict（未跑≠通过，诚实标记）"""
    exec_status = result.get("exec_status", "fail")
    stdout = (result.get("stdout") or "").strip()
    if exec_status != "pass":
        return "unverifiable", f"沙箱未通过（{exec_status}）"
    if "VERIFIED" in stdout:
        return "consistent", ""
    if "REJECTED" in stdout:
        return "inconsistent", ""
    if "UNVERIFIABLE" in stdout:
        return "unverifiable", "推导无法程序化验证"
    # 沙箱通过但无判定标记 → 兜底按不可验证（诚实，不臆断）
    return "unverifiable", "沙箱执行完成但无明确判定输出"


@router.post("/derivations/verify")
async def verify_derivation(
    req: DerivationVerifyRequest,
    user: dict = Depends(require_role("teacher", "researcher")),
    db=Depends(get_db),
):
    """伪代码/推导验证（星辰优先 → 本地降级 → 50301）"""
    user_id = user["sub"]
    request_id = f"deriv-{uuid.uuid4().hex[:12]}"  # 审计链请求号（user 字典无 request_id 键，原实现恒空串）

    # 1. 星辰优先（wf_verify_derivation；三层解析有效配置，管理后台配置即时生效）
    from app.providers.xingchen import resolve_effective_xingchen_config

    xcfg = await resolve_effective_xingchen_config(db, user_id)
    if xcfg.enabled and xcfg.flow_ids.get("wf_verify_derivation"):
        try:
            from app.providers.xingchen import run_workflow

            wf = await run_workflow(
                "wf_verify_derivation",
                uid=user_id,
                parameters={
                    "derivation_text": req.derivation_text,
                    "domain_hint": req.domain_hint or "general",
                    "expected_result": req.expected_result or "",
                },
                config=xcfg,
            )
            verdict = _normalize_verdict(wf.get("verdict"))
            return {
                "code": 0,
                "data": {
                    "verdict": verdict,
                    "steps": wf.get("steps") or [],
                    "generated_code": wf.get("generated_code") or "",
                    "engine": "xingchen",
                },
            }
        except Exception as e:
            logger.warning("verify_derivation.xingchen_failed", error=str(e)[:150])

    # 2. 本地降级：LLM 生成验证代码 + 沙箱执行（公网入口不可用预案的本地直跑形态）
    try:
        from app.providers.router import get_model_router

        llm = get_model_router()
        code = await _generate_verify_code(llm, req, request_id)
        if not code:
            return {"code": 50301, "message": "验证服务暂不可用，请稍后重试"}
        result = await run_sandbox(code, timeout_ms=10000)
        verdict, doubt = _judge_local(code, result, req.expected_result)
        steps = [
            {
                "step_no": 1,
                "claim": "本地自动验证",
                "code": code[:2000],
                "exec_status": result.get("exec_status", "fail"),
                "doubt": doubt,
            }
        ]
        return {
            "code": 0,
            "data": {
                "verdict": verdict,
                "steps": steps,
                "generated_code": code,
                "engine": "local",
            },
        }
    except Exception as e:
        logger.error("verify_derivation.local_failed", error=str(e)[:200])
        return {"code": 50301, "message": "验证服务暂不可用，请稍后重试"}
