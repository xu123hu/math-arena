"""FastAPI 应用入口

只做 app 装配，禁止写业务逻辑（分层铁律 §7.0）。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.providers import get_spark, get_deepseek
from app.providers.embedding import EmbeddingProvider
from app.providers.http import close_http
from app.gateway.redis import close_redis

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动/关闭钩子"""
    logger.info("app.starting", env=settings.app_env)
    yield
    logger.info("app.stopping")
    await close_http()
    await close_redis()


app = FastAPI(
    title="Math Arena API",
    description="数学垂类大模型 - 教学科研智能体平台",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Idempotent-Replay"],
)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """服务健康检查"""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/health/models")
async def model_health_check() -> dict:
    """模型通道健康检查（M0 验收用）

    返回星火/DeepSeek/Embedding 三通道状态。
    对齐 API 文档 §5.2 格式。
    """
    import asyncio

    spark = get_spark()
    deepseek = get_deepseek()
    embedding = EmbeddingProvider()

    # 并发探测三通道
    spark_result, deepseek_result, embedding_result = await asyncio.gather(
        spark.health_check(),
        deepseek.health_check(),
        embedding.health_check(),
    )

    return {
        "spark": spark_result,
        "deepseek": deepseek_result,
        "embedding": embedding_result,
    }


# ========== 注册路由 ==========

from app.gateway.auth_router import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])

from app.gateway.agent_router import router as agent_router
app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])

# TODO: 注册其他路由
# from app.domains.org.router import router as org_router
# from app.domains.classroom.router import router as classroom_router
# from app.domains.ops.router import router as ops_router
# app.include_router(classroom_router, prefix="/api/classes", tags=["班级"])
# app.include_router(ops_router, prefix="/api/ops", tags=["运维"])
