"""文件域路由（SSOT §5.1-5.3 / ADR-M2B-001）

端点：
- POST /api/files/upload — 创建上传（预签名/分片）
- POST /api/files/{id}/complete — 分片完成回调
- GET /api/files/{id} — 解析状态轮询
- POST /api/files/{id}/parse — 触发解析（幂等）
- GET /api/files/{id}/assets/{asset_id}/url — 产物图预签名 URL（ADR-007）
"""

from __future__ import annotations

import hashlib
import secrets
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.gateway.auth import get_current_user
from app.gateway.redis import get_redis
from app.models.database import get_db
from app.models.file import File, FileAsset
from app.providers.storage import get_storage, get_storage_for_user

if TYPE_CHECKING:
    from app.providers.xingchen import XingchenConfig

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

# MIME 白名单（SSOT §5.1 + ADR-015 jsonl）
ALLOWED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/markdown",
    "text/plain",
    "application/jsonl",  # ADR-015: 仅 teacher/researcher
}

# jsonl 仅 teacher/researcher 可用
JSONL_ROLES = {"teacher", "researcher"}

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
LOCAL_UPLOAD_ROOT = Path(tempfile.gettempdir()) / "math-arena-file-uploads"


# ==================== Schemas ====================


class UploadRequest(BaseModel):
    filename: str = Field(..., max_length=255)
    mime: str
    size_bytes: int = Field(..., le=MAX_FILE_SIZE)
    sha256: str = Field(..., min_length=64, max_length=64)
    multipart: bool = False


class UploadResponse(BaseModel):
    file_id: str
    upload_url: str
    upload_id: str | None = None
    part_size: int = 5242880
    expires_in: int = 900
    deduplicated: bool = False


class CompleteRequest(BaseModel):
    upload_id: str | None = None  # 非分片直传（PUT 预签名 URL）时为空
    parts: list[dict] = []  # [{part_no, etag}]，分片上传完成回调时携带


class ParseRequest(BaseModel):
    engine_hint: str = "auto"  # auto/mineru/rapidocr/spark_vl
    purpose: str  # chat_attach/question_photo/kb_ingest


# ==================== 端点 ====================


@router.post("/upload")
async def upload_file(
    req: UploadRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建上传（预签名/分片）"""
    user_id = user["sub"]
    active_role = user.get("active_role", "student")

    # MIME 校验
    if req.mime not in ALLOWED_MIMES:
        return {"code": 40001, "message": f"不支持的文件类型: {req.mime}"}

    # jsonl 角色限制（ADR-015）
    if req.mime == "application/jsonl" and active_role not in JSONL_ROLES:
        return {"code": 40301, "message": "jsonl 上传仅限教师/科研人员"}

    # 大小校验
    if req.size_bytes > MAX_FILE_SIZE:
        return {"code": 40001, "message": "文件大小超过 20MB 限制"}

    # 限流：每用户 10 次/小时
    redis = await get_redis()
    rate_key = f"ratelimit:upload:{user_id}"
    count = await redis.incr(rate_key)
    if count == 1:
        await redis.expire(rate_key, 3600)
    if count > settings.upload_rate_limit_per_hour:
        return {"code": 42901, "message": "上传频率超限（每小时 10 次）"}

    # sha256 去重
    existing = await db.execute(
        select(File).where(
            File.user_id == uuid.UUID(user_id),
            File.sha256 == req.sha256,
            File.deleted_at.is_(None),
        )
    )
    existing_file = existing.scalar_one_or_none()
    if existing_file:
        if settings.app_env == "development" and (
            not (existing_file.storage_uri or "").startswith("local:")
            or not _local_file_path(existing_file).exists()
        ):
            upload_token = secrets.token_urlsafe(24)
            existing_file.storage_uri = f"local:{upload_token}"
            existing_file.status = "uploaded"
            existing_file.error = None
            await db.commit()
            return {
                "code": 0,
                "data": {
                    "file_id": str(existing_file.id),
                    "upload_url": f"/api/files/{existing_file.id}/local-upload?token={upload_token}",
                    "upload_id": None,
                    "part_size": 5242880,
                    "expires_in": 900,
                    "deduplicated": False,
                },
            }
        return {
            "code": 0,
            "data": {
                "file_id": str(existing_file.id),
                "upload_url": "",
                "upload_id": None,
                "part_size": 5242880,
                "expires_in": 0,
                "deduplicated": True,
            },
        }

    # 推导 file_type
    file_type = _mime_to_type(req.mime)

    # 开发环境使用本地上传代理，保证未启动 MinIO 时拍照/附件仍可用。
    # 生产环境保持对象存储预签名上传。
    local_fallback = settings.app_env == "development"
    storage = None if local_fallback else await get_storage_for_user(user_id, db)
    object_key = None if local_fallback else storage.generate_object_key(user_id, req.filename)

    new_file = File(
        user_id=uuid.UUID(user_id),
        filename=req.filename,
        mime=req.mime,
        size_bytes=req.size_bytes,
        sha256=req.sha256,
        storage_uri=object_key,
        file_type=file_type,
        status="uploaded",
    )
    db.add(new_file)
    await db.flush()

    # 生成预签名 URL
    upload_id = None
    if local_fallback:
        upload_token = secrets.token_urlsafe(24)
        new_file.storage_uri = f"local:{upload_token}"
        upload_url = f"/api/files/{new_file.id}/local-upload?token={upload_token}"
    elif req.multipart and req.size_bytes > 5 * 1024 * 1024:
        upload_id = storage.create_multipart_upload(object_key)
        upload_url = storage.presign_upload_part(object_key, upload_id, 1)
    else:
        upload_url = storage.presign_put(object_key)

    await db.commit()

    return {
        "code": 0,
        "data": {
            "file_id": str(new_file.id),
            "upload_url": upload_url,
            "upload_id": upload_id,
            "part_size": 5242880,
            "expires_in": 900 if local_fallback else storage.presign_expires,
            "deduplicated": False,
        },
    }


@router.put("/{file_id}/local-upload")
async def local_upload_content(file_id: uuid.UUID, token: str, request: Request, db: AsyncSession = Depends(get_db)):
    """开发环境本地 PUT 降级；随机 token 具备与预签名 URL 相同的上传授权语义。"""
    if settings.app_env != "development":
        return {"code": 40400, "message": "上传地址不存在"}
    file_obj = await db.get(File, file_id)
    expected = (file_obj.storage_uri or "").removeprefix("local:") if file_obj else ""
    if not file_obj or not expected or not secrets.compare_digest(expected, token):
        return {"code": 40301, "message": "上传地址无效或已过期"}
    data = await request.body()
    if len(data) != file_obj.size_bytes or len(data) > MAX_FILE_SIZE:
        return {"code": 40001, "message": "上传文件大小不匹配"}
    if hashlib.sha256(data).hexdigest() != file_obj.sha256:
        return {"code": 40001, "message": "上传文件校验失败"}
    path = _local_file_path(file_obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    file_obj.status = "uploaded"
    await db.commit()
    return {"code": 0, "data": {"file_id": str(file_id), "status": "uploaded"}}


@router.post("/{file_id}/complete")
async def complete_upload(
    file_id: uuid.UUID,
    req: CompleteRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分片完成回调（迭代18 修复：非分片直传幂等确认，不再误走分片合并报 50001）"""
    file_obj = await _get_user_file(file_id, user["sub"], db)
    if not file_obj:
        return {"code": 40400, "message": "文件不存在"}

    # 非分片直传：PUT 预签名 URL 已完成，complete 仅作幂等确认
    if not req.upload_id:
        return {"code": 0, "data": {"file_id": str(file_id), "status": "uploaded"}}

    storage = await get_storage_for_user(user["sub"], db)
    try:
        storage.complete_multipart_upload(file_obj.storage_uri, req.upload_id, req.parts)
    except Exception as e:
        logger.error("multipart_complete_failed", file_id=str(file_id), error=str(e))
        return {"code": 50001, "message": "分片合并失败"}

    return {"code": 0, "data": {"file_id": str(file_id), "status": "uploaded"}}


@router.get("/{file_id}")
async def get_file_status(
    file_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """解析状态轮询"""
    file_obj = await _get_user_file(file_id, user["sub"], db)
    if not file_obj:
        return {"code": 40400, "message": "文件不存在"}

    # 查询 assets
    assets_result = await db.execute(
        select(FileAsset).where(
            FileAsset.file_id == file_id,
            FileAsset.deleted_at.is_(None),
        )
    )
    assets = assets_result.scalars().all()

    assets_data = []
    for a in assets:
        item = {
            "asset_id": str(a.id),
            "asset_type": a.asset_type,
            "page_no": a.page_no,
        }
        # ADR-007: markdown/text 带 content，page_image 带 storage_uri
        if a.asset_type in ("markdown", "text"):
            item["content"] = a.content
        elif a.asset_type == "page_image":
            item["storage_uri"] = a.storage_uri
        assets_data.append(item)

    return {
        "code": 0,
        "data": {
            "file_id": str(file_obj.id),
            "filename": file_obj.filename,
            "status": file_obj.status,
            "parse_engine": file_obj.parse_engine,
            "parse_quality": file_obj.parse_quality,
            "error": file_obj.error,
            "assets": assets_data,
            "created_at": file_obj.created_at.isoformat() if file_obj.created_at else None,
            "updated_at": file_obj.updated_at.isoformat() if file_obj.updated_at else None,
        },
    }


@router.post("/{file_id}/parse")
async def parse_file(
    file_id: uuid.UUID,
    req: ParseRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发解析（幂等）"""
    file_obj = await _get_user_file(file_id, user["sub"], db)
    if not file_obj:
        return {"code": 40400, "message": "文件不存在"}

    # 幂等：已 parsed 直接返回
    if file_obj.status == "parsed":
        return {"code": 0, "data": {"file_id": str(file_id), "status": "parsed", "task_id": None}}

    # 开发环境本地照片采用即时人工复核降级：原图已可靠保存，不等待 OCR/外部视觉。
    if req.purpose == "question_photo" and (file_obj.storage_uri or "").startswith("local:"):
        file_obj.status = "parsed"
        file_obj.parse_engine = "manual_photo_review"
        file_obj.parse_quality = {
            "sampled_pages": 1,
            "confidence": 0.0,
            "fallback": "manual_photo_review",
        }
        file_obj.error = None
        await db.commit()
        return {
            "code": 0,
            "data": {"file_id": str(file_id), "status": "parsed", "task_id": None},
        }

    # parsing 中重复调用 → 40901
    if file_obj.status == "parsing":
        return {"code": 40901, "message": "文件正在解析中"}

    # 更新状态
    file_obj.status = "parsing"
    await db.commit()

    # 后台解析任务
    task_id = uuid.uuid4().hex
    background_tasks.add_task(_run_parse_task, str(file_id), req.engine_hint, req.purpose)

    return {"code": 0, "data": {"file_id": str(file_id), "status": "parsing", "task_id": task_id}}


@router.get("/{file_id}/assets/{asset_id}/url")
async def get_asset_url(
    file_id: uuid.UUID,
    asset_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """产物图预签名 GET URL（ADR-007）"""
    file_obj = await _get_user_file(file_id, user["sub"], db)
    if not file_obj:
        return {"code": 40400, "message": "文件不存在"}

    asset = await db.get(FileAsset, asset_id)
    if not asset or asset.file_id != file_id or asset.deleted_at:
        return {"code": 40400, "message": "产物不存在"}

    if not asset.storage_uri:
        return {"code": 40400, "message": "该产物无存储对象"}

    storage = await get_storage_for_user(user["sub"], db)
    try:
        url = storage.presign_get(asset.storage_uri)
    except Exception as e:
        logger.error("asset_url_presign_failed", asset_id=str(asset_id), error=str(e)[:200])
        return {"code": 50301, "message": "存储服务暂不可用，请稍后再试"}
    return {"code": 0, "data": {"url": url, "expires_in": storage.presign_expires}}


@router.get("/{file_id}/content")
async def get_file_content(
    file_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """原文件预签名 GET URL（M2 §2.10：前端图片缩略图与 PDF 预览用；仅属主）"""
    file_obj = await _get_user_file(file_id, user["sub"], db)
    if not file_obj:
        return {"code": 40400, "message": "文件不存在"}

    if not file_obj.storage_uri:
        return {"code": 40400, "message": "该文件无存储对象"}

    storage = await get_storage_for_user(user["sub"], db)
    try:
        url = storage.presign_get(file_obj.storage_uri)
    except Exception as e:
        # 存储未配置/不可用 → 结构化错误（前端降级图标 chip），绝不裸 500
        logger.error("file_content_presign_failed", file_id=str(file_id), error=str(e)[:200])
        return {"code": 50301, "message": "存储服务暂不可用，请稍后再试"}
    return {
        "code": 0,
        "data": {
            "url": url,
            "expires_in": storage.presign_expires,
            "mime": file_obj.mime,
            "name": file_obj.filename,
        },
    }


# ==================== 内部工具 ====================


async def _get_user_file(file_id: uuid.UUID, user_id: str, db: AsyncSession) -> File | None:
    """获取用户文件（越权返 None → 404）"""
    result = await db.execute(
        select(File).where(
            File.id == file_id,
            File.user_id == uuid.UUID(user_id),
            File.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


def _mime_to_type(mime: str) -> str:
    """MIME → file_type 映射"""
    mapping = {
        "application/pdf": "pdf",
        "image/jpeg": "image",
        "image/png": "image",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "text/markdown": "md",
        "text/plain": "txt",
        "application/jsonl": "jsonl",
    }
    return mapping.get(mime, "unknown")


async def _run_parse_task(file_id: str, engine_hint: str, purpose: str) -> None:
    """后台解析任务（M2 用 BackgroundTasks + 独立 session；迭代05：后台专用 NullPool 工厂）"""
    from app.models.database import background_session_factory

    try:
        async with background_session_factory() as db:
            file_obj = await db.get(File, uuid.UUID(file_id))
            if not file_obj:
                return

            # 星辰有效配置（三层解析，管理后台配置即时生效；文件属主的用户覆盖层一并生效）
            from app.providers.xingchen import resolve_effective_xingchen_config

            xcfg = await resolve_effective_xingchen_config(db, str(file_obj.user_id))

            # 路由解析引擎
            engine = _resolve_engine(file_obj.file_type, engine_hint)
            file_obj.parse_engine = engine

            # 执行解析（按引擎分发）
            content = await _dispatch_parse(file_obj, engine, purpose, config=xcfg)
            confidence = 0.0

            # image 双轨（迭代18 调序，SSOT §5.3 决策表 #4 增强）：
            # ① question_photo（拍照题）优先走 wf_doc_understand 云轨——RapidOCR 对数学
            #   公式结构还原失真（实测 f'(1)→f(1)、x²→x~2），云轨输出 LaTeX + confidence；
            # ② 其他 image purpose 保持原兑底：本地 OCR 无有效文字且星辰可用才升级云轨。
            if file_obj.file_type == "image" and purpose == "question_photo":
                vision_text, vision_conf = await _parse_image_vision(file_obj, config=xcfg)
                if vision_text:
                    content = vision_text
                    confidence = vision_conf
                    file_obj.parse_engine = "spark_vl"
            if (
                file_obj.file_type == "image"
                and file_obj.parse_engine == "rapidocr"
                and (content is None or len(content.strip()) < _RAPIDOCR_MIN_TEXT_LEN)
            ):
                vision_text, vision_conf = await _parse_image_vision(file_obj, config=xcfg)
                if vision_text:
                    content = vision_text
                    confidence = vision_conf
                    file_obj.parse_engine = "spark_vl"

            if content:
                # 写入 file_assets
                asset = FileAsset(
                    file_id=file_obj.id,
                    asset_type="markdown" if engine != "rapidocr" else "text",
                    page_no=1,
                    content=content,
                )
                db.add(asset)
                file_obj.status = "parsed"
                file_obj.parse_quality = {"sampled_pages": 1, "confidence": round(confidence, 4)}
            elif purpose == "question_photo":
                # OCR/外部视觉均不可用时仍保留原图，转教师人工复核而不是丢弃文件。
                file_obj.status = "parsed"
                file_obj.parse_quality = {"sampled_pages": 1, "confidence": 0.0, "fallback": "manual_photo_review"}
            else:
                file_obj.status = "failed"
                file_obj.error = "解析无输出"

            await db.commit()
            logger.info("file_parsed", file_id=file_id, engine=engine)

    except Exception as e:
        logger.error("file_parse_failed", file_id=file_id, error=str(e))
        try:
            async with background_session_factory() as db:
                file_obj = await db.get(File, uuid.UUID(file_id))
                if file_obj:
                    file_obj.status = "failed"
                    file_obj.error = str(e)[:500]
                    await db.commit()
        except Exception:
            pass


def _resolve_engine(file_type: str, hint: str) -> str:
    """解析引擎路由（SSOT §5.3 决策表 #1-4）"""
    if hint != "auto":
        return hint

    if file_type == "pdf":
        return "pymupdf"  # 默认 PyMuPDF，复杂走 MinerU（未部署时降级 PyMuPDF）
    elif file_type == "image":
        return "rapidocr"  # 纯文字 RapidOCR；OCR 无有效文字时自动升级 spark_vl 云轨（双轨兑底）
    elif file_type in ("docx", "pptx", "xlsx"):
        return "pandoc"
    elif file_type in ("md", "txt"):
        return "direct"
    return "pymupdf"


# OCR 有效文字下限：低于此长度视为未识别到有效文字，触发云轨兑底（SSOT §5.3 双轨）
_RAPIDOCR_MIN_TEXT_LEN = 20


def _local_file_path(file_obj: File) -> Path:
    return LOCAL_UPLOAD_ROOT / str(file_obj.user_id) / f"{file_obj.id}.bin"


def _read_file_bytes(file_obj: File) -> bytes:
    if (file_obj.storage_uri or "").startswith("local:"):
        return _local_file_path(file_obj).read_bytes()
    return get_storage().get_bytes(file_obj.storage_uri)


async def _parse_pdf_pymupdf(file_obj: File) -> str | None:
    """PDF 文本层解析（PyMuPDF，SSOT §5.3 决策表 #1）"""
    try:
        import fitz  # PyMuPDF

        data = _read_file_bytes(file_obj)
        doc = fitz.open(stream=data, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("pymupdf_not_installed")
        return None
    except Exception as e:
        logger.error("pymupdf_parse_error", error=str(e))
        return None


async def _parse_image_rapidocr(file_obj: File) -> str | None:
    """纯文字图片 OCR（RapidOCR ONNX，CPU 毫秒级；SSOT §5.3 决策表 #4 本地轨）

    返回识别文本；无识别结果返回空串（区别于 None=依赖/执行异常）。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        logger.warning("rapidocr_not_installed", hint="pip install rapidocr_onnxruntime")
        return None
    try:
        data = _read_file_bytes(file_obj)
        ocr = RapidOCR()
        result, _elapse = ocr(data)
        if not result:
            return ""
        # result: [[box, text, score], ...]
        return "\n".join(str(item[1]) for item in result)
    except Exception as e:
        logger.error("rapidocr_parse_error", error=str(e))
        return None


async def _parse_image_vision(file_obj: File, config: XingchenConfig | None = None) -> tuple[str | None, float]:
    """图片理解云轨（wf_doc_understand，SSOT §4.2：含图形/手写/几何题）

    星辰不可用/输出非法 → (None, 0.0)（调用方降级 RapidOCR 兑底 + badge ocr_fallback）。
    confidence<0.6 低置信闸门：仍返回已识别文本但记录日志，由业务层提示确认（铁律 4：不静默使用）。
    config 为调用方三层解析后的有效配置（管理后台配置即时生效），缺省走 env。

    返回 (text, confidence)：text 含 LaTeX 片段；confidence 供 parse_quality 落库。
    """
    from app.providers.xingchen import xingchen_config_from_settings

    cfg = config or xingchen_config_from_settings()
    if not cfg.enabled:
        return None, 0.0
    try:
        # 迭代19 修复（任务9）：星辰文件上传服务 /workflow/v1/files 已下线（404），
        # 工作流实测支持 data URI 直传图片（2026-08-15 探测 code=0），
        # 不再依赖文件服务——读取 MinIO 字节 → base64 data URI → image_url 参数。
        import base64

        from app.providers.xingchen import run_workflow

        data = _read_file_bytes(file_obj)
        data_uri = f"data:{file_obj.mime or 'image/png'};base64," + base64.b64encode(data).decode("ascii")
        result = await run_workflow(
            "wf_doc_understand",
            uid=str(file_obj.user_id),
            parameters={
                "AGENT_USER_INPUT": "解析试卷题目并提取 LaTeX",
                "image_url": data_uri,
                "task": "extract_question",
                "grade_hint": "G3",
            },
            config=cfg,
        )
        question_text = (result.get("question_text") or "").strip()
        fragments = result.get("latex_fragments") or []
        confidence = float(result.get("confidence") or 0.0)
        if confidence < 0.6:
            logger.info("doc_understand_low_confidence", confidence=confidence)
        parts = [question_text]
        if fragments:
            parts.append("（图片识别出的公式片段：" + "；".join("$" + f + "$" for f in fragments) + "）")
        text = "\n".join(p for p in parts if p).strip()
        return (text or None), confidence
    except Exception as e:
        logger.warning("doc_understand_failed_fallback", error=str(e)[:200])
        return None, 0.0


async def _parse_office_pandoc(file_obj: File) -> str | None:
    """Office 文档转换（pandoc；失败→python-docx 兑底抽取纯文本，SSOT §5.3 决策表 #3）"""
    import asyncio as _asyncio
    import os
    import tempfile

    data = _read_file_bytes(file_obj)
    in_fmt = {"docx": "docx", "pptx": "pptx", "xlsx": "xlsx"}.get(file_obj.file_type)

    # 1) pandoc 子进程
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=f".{file_obj.file_type}", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        proc = await _asyncio.create_subprocess_exec(
            "pandoc",
            tmp_path,
            "-f",
            in_fmt,
            "-t",
            "markdown",
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.PIPE,
        )
        stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0 and stdout.strip():
            return stdout.decode("utf-8", errors="replace")
    except FileNotFoundError:
        logger.info("pandoc_not_installed", hint="安装 pandoc 可执行文件以启用 Office 解析")
    except Exception as e:
        logger.warning("pandoc_parse_error", error=str(e)[:150])
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # 2) python-docx 兑底（仅 docx，逐段抽取纯文本）
    if file_obj.file_type == "docx":
        try:
            import io as _io

            import docx

            doc = docx.Document(_io.BytesIO(data))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text or None
        except ImportError:
            logger.warning("python_docx_not_installed", hint="pip install python-docx")
        except Exception as e:
            logger.error("docx_fallback_error", error=str(e)[:150])
    return None


async def _dispatch_parse(
    file_obj: File, engine: str, purpose: str, config: XingchenConfig | None = None
) -> str | None:
    """分发解析（迭代05：全引擎真实接线，无占位符）；config 透传云轨星辰有效配置"""
    if engine == "direct":
        # md/txt 直读
        try:
            data = _read_file_bytes(file_obj)
            return data.decode("utf-8", errors="replace")
        except Exception:
            return None

    if engine == "pymupdf":
        return await _parse_pdf_pymupdf(file_obj)

    if engine == "mineru":
        # MinerU pipeline 未部署：契约保留，本地降级 PyMuPDF（迭代05 口径）
        logger.warning("mineru_not_deployed_fallback_pymupdf")
        return await _parse_pdf_pymupdf(file_obj)

    if engine == "rapidocr":
        return await _parse_image_rapidocr(file_obj)

    if engine == "spark_vl":
        # 显式指定云轨：直接 wf_doc_understand，失败降级 RapidOCR（SSOT §4.2 降级链）
        # 迭代19 修复：_parse_image_vision 已改为返回 (text, confidence) 二元组，
        # 旧代码直接 `if content:` 恒真 + 把元组当文本返回（显式 spark_vl 链路解析结果被污染）。
        content, _confidence = await _parse_image_vision(file_obj, config=config)
        if content:
            return content
        logger.info("spark_vl_fallback_rapidocr")
        return await _parse_image_rapidocr(file_obj)

    if engine == "pandoc":
        return await _parse_office_pandoc(file_obj)

    return None
