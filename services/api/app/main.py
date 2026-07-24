"""FastAPI 应用入口

只做 app 装配，禁止写业务逻辑（分层铁律 §7.0）。
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.domains.classroom.router import router as classroom_router
from app.domains.ops.router import router as ops_router
from app.gateway.agent_router import router as agent_router
from app.gateway.auth_router import router as auth_router
from app.gateway.redis import close_redis
from app.models.database import async_session_factory
from app.providers import get_deepseek, get_spark
from app.providers.embedding import EmbeddingProvider
from app.providers.http import close_http
from app.skills.registry import get_skill_registry, register_builtin_skills

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动/关闭钩子"""
    # 生产环境安全配置校验（弱 JWT 密钥等直接拒绝启动）
    settings.validate_production()
    logger.info("app.starting", env=settings.app_env)
    # 表结构由 Alembic 迁移管理，禁止 create_all 双轨
    # 注册内置 Skills
    register_builtin_skills()
    # 同步 Skills 到数据库（skill_runs 外键依赖）
    registry = get_skill_registry()
    async with async_session_factory() as session:
        await registry.sync_to_db(session)
        await session.commit()
    logger.info("app.skills_registered")
    yield
    logger.info("app.stopping")
    await close_http()
    await close_redis()


app = FastAPI(
    title="Math Arena API",
    description="数学垂类大模型 - 教学科研智能体平台",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置：白名单制（凭证模式下禁止 "*"）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id", "X-Idempotent-Replay"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """422 统一为业务信封格式（§4.1）"""
    try:
        errors = jsonable_encoder(exc.errors())
    except Exception:
        errors = []
    return JSONResponse(
        status_code=422,
        content={
            "code": 40001,
            "message": "请求参数格式错误",
            "requestId": request.headers.get("X-Request-Id") or str(uuid.uuid4()),
            "data": {"errors": errors},
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常统一格式（429 等自定义 detail 直接透传）"""
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code * 100 + 1, "message": str(exc.detail)},
    )


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/health/models")
async def model_health_check() -> dict:
    """模型通道健康检查"""
    import asyncio

    spark = get_spark()
    deepseek = get_deepseek()
    embedding = EmbeddingProvider()

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

app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])
app.include_router(classroom_router, prefix="/api/classes", tags=["班级"])
app.include_router(ops_router, prefix="/api/ops", tags=["运维"])
