"""FastAPI 应用入口

只做 app 装配，禁止写业务逻辑（分层铁律 §7.0）。
"""

import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

# Windows 控制台默认 GBK：日志含 U+2212（−）等 GBK 不支持的字符时
# print/structlog 会抛 UnicodeEncodeError 并中断请求链路（曾致 RAG 检索静默失败）。
# 启动时统一改为 UTF-8 + replace 兜底；reconfigure 就地生效，已持有引用的 handler 同样受益。
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.domains.classroom.course_router import router as course_router
from app.domains.classroom.router import router as classroom_router
from app.domains.classroom.stage_router import router as classroom_stage_router
from app.domains.files.router import router as files_router
from app.domains.identity.admin_router import router as identity_admin_router
from app.domains.identity.router import profile_router as identity_profile_router
from app.domains.identity.router import router as identity_auth_router
from app.domains.model_config.router import router as model_config_router
from app.domains.ops.router import router as ops_router
from app.gateway.admin_router import router as admin_router
from app.gateway.agent_router import router as agent_router
from app.gateway.auth_router import router as auth_router
from app.gateway.butler_router import router as butler_router
from app.gateway.class_ext_router import router as class_ext_router
from app.gateway.exam_router import router as exam_router
from app.gateway.growth_router import agent_ext_router as growth_agent_ext_router
from app.gateway.growth_router import router as growth_router
from app.gateway.integration_router import router as integration_router
from app.gateway.kb_router import router as kb_router
from app.gateway.ops_ext_router import router as ops_ext_router
from app.gateway.redis import close_redis
from app.gateway.research_router import router as research_router
from app.gateway.search_router import router as search_router
from app.gateway.speech_router import router as speech_router
from app.gateway.student_router import router as student_router
from app.gateway.tools_router import router as tools_router
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
        return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code * 100 + 1, "message": str(exc.detail)},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """未捕获异常兜底：返回 JSON 信封，避免前端解析失败"""
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    logger.error("unhandled_exception", path=request.url.path, error=str(exc)[:500], request_id=request_id)
    return JSONResponse(
        status_code=500,
        content={
            "code": 50000,
            "message": "服务器内部错误，请稍后重试",
            "requestId": request_id,
            "data": None,
        },
    )


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/health/models")
async def model_health_check(request: Request) -> dict:
    """模型通道健康检查（支持 per-user 配置）

    携带 Bearer token 时按用户自定义配置探测，否则用全局 .env 配置。
    """
    import asyncio

    from app.providers.router import get_model_router_for_user

    # 尝试解析用户（可选认证，失败不报错）
    spark = get_spark()
    deepseek = get_deepseek()

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from app.gateway.jwt import decode_token

            payload = decode_token(auth_header[7:])
            user_id = payload.get("sub")
            if user_id:
                async with async_session_factory() as session:
                    user_router = await get_model_router_for_user(user_id, session)
                    spark = user_router._spark
                    deepseek = user_router._deepseek
        except Exception:
            pass  # token 无效时回退全局

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

# M0-M1 既有路由
app.include_router(auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(identity_auth_router, prefix="/api/auth", tags=["认证"])
app.include_router(identity_profile_router, prefix="/api/identity", tags=["身份"])
app.include_router(identity_admin_router, prefix="/api/admin/identity", tags=["身份审核"])
app.include_router(agent_router, prefix="/api/agent", tags=["智能体"])
app.include_router(classroom_router, prefix="/api/classes", tags=["班级"])
app.include_router(course_router)  # /api/courses/*（迭代05 阶段4：F9 双师课堂预处理管线）
app.include_router(classroom_stage_router)  # /api/classroom/*（AI 数学课堂：大纲→逐页内容两段式生成）
app.include_router(ops_router, prefix="/api/ops", tags=["运维"])
app.include_router(model_config_router, prefix="/api/model-config", tags=["模型配置"])
app.include_router(integration_router, prefix="/api/integrations", tags=["集成配置"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])  # 管理后台配置

# M2 新增路由
app.include_router(files_router)  # /api/files/*（自带 prefix）
app.include_router(speech_router)  # /api/agent/speech/*（自带 prefix）
app.include_router(search_router)  # /api/search/*（自带 prefix）
# M2 迭代16 学情增长聚合：置于 student_router 之前，
# 避免 /error-records/filter 等静态路径被 {record_id} 形式的路径参数抢占
app.include_router(growth_router)  # /api/student/growth|practice|error-records|report|knowledge-graph/*（自带 prefix）
app.include_router(growth_agent_ext_router)  # /api/agent/route-intent（自带 prefix）
app.include_router(class_ext_router)  # /api/classes/{id}/feed|hot-errors、/api/student/resources/recommend（迭代16 第二批模块7）
app.include_router(student_router)  # /api/student/*（自带 prefix）
app.include_router(exam_router)  # /api/student/exam/*（模拟试卷/专题训练，自带 prefix）
app.include_router(butler_router)  # /api/butler/*（AI 管家调度层，自带 prefix）
app.include_router(ops_ext_router)  # /api/ops/xingchen/*（自带 prefix）
app.include_router(tools_router)  # /tools/*（X-Tool-Key 鉴权，自带 prefix）
app.include_router(kb_router)  # /api/kb/*（迭代05：知识库试点五端点，teacher/researcher）
# 科研端（F14 wf_verify_derivation）按 feature profile 挂载：
# M2 默认（m2_enable_research=False）不暴露 /api/research/*；M4 科研端置 true 后自动恢复。
# 科研代码不删除，仅控制路由面（阶段 1 契约护栏，见 tests/test_m2_route_profile.py）。
if settings.m2_enable_research:
    app.include_router(research_router)  # /api/research/*（迭代06：wf_verify_derivation 科研端试点落地，自带 prefix）

# M3 教师端按 feature profile 挂载（默认 m3_enable_teacher=False，不干扰 M2/学生端）。
# 教师端仅服务高中日常教学，不含科研评审/建模教练能力。
if settings.m3_enable_teacher:
    from app.domains.teacher.router import router as teacher_router

    app.include_router(teacher_router)  # /api/teacher/*（教师端，自带 prefix）
