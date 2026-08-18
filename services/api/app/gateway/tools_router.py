"""工具门面路由（SSOT §5.9 / X-Tool-Key 鉴权）

端点：
- POST /tools/verify/run — SymPy 沙箱执行（星辰回调 + 本地 Skill 共用）
- POST /tools/retrieve — 知识库检索扩展（mode 参数）
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from app.config import settings
from app.providers.sandbox import run_sandbox

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


class VerifyRunRequest(BaseModel):
    code: str = Field(..., max_length=4000)
    timeout_ms: int = Field(default=10000, le=10000)


class RetrieveRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # hybrid/vector/fulltext/kp
    content_type: str | None = None
    kp_codes: list[str] | None = None
    top_k: int = Field(default=4, le=10)


def _check_tool_key(x_tool_key: str) -> dict | None:
    """X-Tool-Key 校验，失败返回错误响应"""
    if not settings.tool_api_key:
        return {"code": 50301, "message": "工具密钥未配置（TOOL_API_KEY）"}
    if x_tool_key != settings.tool_api_key:
        return {"code": 40301, "message": "无效的工具密钥"}
    return None


@router.post("/verify/run")
async def verify_run(
    req: VerifyRunRequest,
    x_tool_key: str = Header(default=""),
):
    """SymPy 沙箱执行（SSOT §5.9）

    星辰自定义托管插件回调入口 + 本地 Skill 共用。
    限时/限内存/禁网。
    """
    # 鉴权
    err = _check_tool_key(x_tool_key)
    if err:
        return err

    result = await run_sandbox(req.code, timeout_ms=req.timeout_ms)

    return {
        "code": 0,
        "data": {
            "exec_status": result["exec_status"],
            "stdout": result["stdout"],
            "result_repr": result["result_repr"],
            "error": result["error"],
        },
    }


@router.post("/retrieve")
async def tools_retrieve(
    req: RetrieveRequest,
    x_tool_key: str = Header(default=""),
):
    """知识库检索扩展（SSOT §5.9 统一门面）

    本地 Skill 与星辰工作流共用。
    mode: hybrid（三路全开）/ vector / fulltext / kp（单路调试）
    content_type/kp_codes 元数据过滤（迭代05 接线：先过滤再向量匹配）。
    """
    # 鉴权
    err = _check_tool_key(x_tool_key)
    if err:
        return err

    # 调用 kernel/rag.py（复用 M1 既有管线；RAGPipeline 无参，db 走 retrieve 关键字参数）
    try:
        from app.kernel.rag import get_rag_pipeline
        from app.models.database import async_session_factory

        async with async_session_factory() as db:
            result = await get_rag_pipeline().retrieve(
                req.query,
                db=db,
                mode=req.mode,
                content_type=req.content_type,
                kp_codes=req.kp_codes,
            )

        chunks = [
            {
                "chunk_id": c.chunk_id,
                "content": c.content[:500],
                "score": c.score,
                "raw_score": c.raw_score,
                "kp_codes": c.kp_ids,
                "doc_title": c.doc_title,
            }
            for c in result.chunks[: req.top_k]
        ]

        return {
            "code": 0,
            "data": {
                "chunks": chunks,
                "answerable": result.answerable,
                "gate": {
                    "top1_score": result.chunks[0].score if result.chunks else 0.0,
                    "threshold": settings.rag_refuse_threshold,
                },
            },
        }

    except Exception as e:
        logger.error("tools_retrieve_failed", error=str(e))
        return {"code": 50001, "message": f"检索失败: {str(e)[:100]}"}
