"""AI 数学课堂会话路由（F9+ 双师课堂：OpenMAIC 融合改造第一阶段）

两段式生成（对齐 OpenMAIC outlines→scene-content 结构，收敛为高中数学专属）：
1. 大纲（outline）：以课程预处理产物（章节/知识点/知识卡）为输入，生成 slide_count 页
   数学课堂大纲：导入→概念/公式→例题→变式→小结，逐页带旁白与建议用时。
2. 逐页内容（content）：每个 outline 生成 blocks（text/latex/example/note）+ 旁白。

纪律（复用 course_router 治理经验）：
- kp_code 只能取自课程锚定（白名单），禁止编造；
- 公式一律 LaTeX（$...$），数学对象校验交给渲染层；
- 输出必须是 JSON，解析失败走确定性兜底（不空手返回）。

端点：
- POST /api/classroom/sessions — 创建会话（后台生成，幂等策略：每请求新会话）
- GET  /api/classroom/sessions — 我的会话列表
- GET  /api/classroom/sessions/{id} — 会话详情（outlines + slides + status）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gateway.auth import get_current_user
from app.gateway.schemas import ApiResponse
from app.models.classroom import ClassroomSession
from app.models.course import COURSE_STATUS_READY, Course
from app.models.database import background_session_factory, get_db
from app.models.knowledge_point import KnowledgePoint

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/classroom", tags=["classroom"])

# ==================== 常量 ====================
MIN_SLIDES = 8
MAX_SLIDES = 15
_MODE_LABELS = {"sync": "同步课堂", "review": "考前复习", "topic": "专题精讲"}

# 高中数学课堂大纲 prompt（数学专属：章节目奏 + 公式 LaTeX + 考点纪律）
_MATH_OUTLINE_PROMPT = """\
你是高中数学主讲老师。基于给定课程的【章节/知识点/知识卡】生成一节课的 AI 课堂大纲，共 {slide_count} 页幻灯片。

【课程章节】
{chapters}

【知识点白名单（kp_codes 只能从此表选择，禁止编造）】
{kp_table}

【课程知识卡（核心概念/公式）】
{knowledge_cards}

【课堂模式】{mode_label}

【大纲 JSON 契约】
{{
  "title": "课堂标题（≤20字）",
  "slides": [
    {{
      "order": 1,
      "type": "slide",
      "title": "页标题（≤12字）",
      "subtitle": "页副题（≤20字，可空）",
      "kp_code": "从白名单选择，無匹配填空串",
      "key_points": ["要点1", "要点2", "要点3"],
      "narration": "旁白（≤120字，口语化，面向学生讲解）",
      "minutes": 2
    }}
  ]
}}

【课堂结构纪律】
1. 第一页必须是"课堂导入"：回顾旧知、抛出本节课要解决的问题；
2. 中间页按学习节奏组织：概念→公式→例题→变式/易错，禁止堆砌；
3. 最后一页必须是"课堂小结"：核心公式 + 易错提醒 + 课后行动（练什么考点）；
4. 每页 2-3 个要点，每页预计用时 2-4 分钟；全课合计约 {total_minutes} 分钟；
5. {count_rule}
6. 只输出 JSON，不要其他文字。"""

# 逐页内容 prompt（复用大纲的故事线 + 知识卡上下文，生成可渲染 blocks）
_MATH_CONTENT_PROMPT = """\
你是高中数学主讲老师。为下面这一页幻灯片写出可渲染的课堂内容。

【本页大纲】
{outline_json}

【课程知识卡参考（概念/公式/例题语境）】
{knowledge_cards}

【输出的 JSON（只输出 JSON）】
{{
  "blocks": [
    {{"kind": "text", "text": "一句话讲解（≤80字，口语化）"}},
    {{"kind": "latex", "latex": "LaTeX 公式（不含 $，如 y = ax^2 + bx + c, \\\\; a \\\\neq 0）"}},
    {{"kind": "example", "question": "例题题干（≤60字）", "analysis": "解题思路（≤80字）", "answer": "答案/结论（≤60字，含 LaTeX 可带 $）"}},
    {{"kind": "note", "text": "易错点/记忆口诀（≤50字）"}}
  ],
  "narration": "本页旁白（≤120字，口语化连续讲解，与大纲旁白可不同）"
}}

【纪律】
- blocks 至少 2 个：必须包含 text；公式页要含 latex；例题页要含 example；
- 名词/公式必须与高中数学一致，禁止编造定理；LaTeX 必须语法正确；
- 只输出 JSON。"""


# ==================== Schemas ====================


class SessionCreateRequest(BaseModel):
    """OpenMAIC 语义：给出 topic 即可生成课堂；course_id 仅作可选增强上下文。"""

    course_id: uuid.UUID | None = None
    topic: str | None = None
    description: str | None = None  # 补充要求：重点讲解/易错点/例题量等
    slide_count: int = Field(default=10, ge=MIN_SLIDES, le=MAX_SLIDES)
    mode: str = Field(default="sync", pattern="^(sync|review|topic)$")

    @model_validator(mode="after")
    def _need_source(self) -> "SessionCreateRequest":
        if self.course_id is None and not (self.topic or "").strip():
            raise ValueError("course_id 与 topic 至少提供一个（OpenMAIC 语义：输入主题即可生成）")
        return self


class SessionItem(BaseModel):
    session_id: str
    course_id: str
    title: str
    mode: str
    slide_count: int
    status: str
    created_at: str | None = None


# ==================== 生成管线 ====================


async def _gen_outline(
    course: Course | None,
    slide_count: int,
    mode: str,
    kp_table: str,
    knowledge_cards: str,
    topic: str = "",
    description: str = "",
) -> tuple[bool, list, str]:
    """大纲生成（LLM → JSON；失败返回确定性兜底大纲）。
    OpenMAIC 语义：course 可空——主题直接生成，课程产物仅作增强上下文。"""
    from app.providers.router import get_model_router
    from app.skills.smart_quiz.main import parse_quiz_json

    if course is not None and (course.preprocess_result or {}).get("chapters"):
        chapters = "；".join(
            f"{ch.get('title')}（{ch.get('summary') or ''}）"
            for ch in (course.preprocess_result or {}).get("chapters") or []
        )
    else:
        chapters = (topic or "").strip()
        if (description or "").strip():
            chapters += f"；补充要求：{description.strip()}"
        chapters = chapters or "（自由生成：请围绕主题组织课堂结构）"
    count_rule = (
        f"slide_count 必须恰好 {slide_count} 页（第一页导入、最后一页小结，中间 {slide_count - 2} 页正文）"
    )
    prompt = _MATH_OUTLINE_PROMPT.format(
        slide_count=slide_count,
        total_minutes=slide_count * 3,
        chapters=chapters[:3000],
        kp_table=kp_table or "（无）",
        knowledge_cards=knowledge_cards[:2000],
        mode_label=_MODE_LABELS.get(mode, "同步课堂"),
        count_rule=count_rule,
    )
    router_llm = get_model_router()
    try:
        result = await router_llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=6000,
            request_id=f"classroom-outline-{uuid.uuid4().hex[:12]}",
            scene="classroom_outline",
        )
        data = parse_quiz_json(result.get("content", "")) or {}
    except Exception as e:
        logger.warning("classroom_outline_llm_failed", error=str(e)[:200])
        data = {}

    slides = data.get("slides") or []
    if not slides:
        # 确定性兜底：按章节/主题切页（第一页导入/最后一页小结）
        slides = _fallback_outline(course, slide_count, topic)
    # 白名单过滤 + 强制 count
    valid_codes = {c.split(":")[0] for c in kp_table.splitlines() if ":" in c}
    keep = []
    for s in slides[: slide_count]:
        keep.append(
            {
                "order": len(keep) + 1,
                "type": "slide",
                "title": str(s.get("title") or f"第 {len(keep) + 1} 页")[:12],
                "subtitle": str(s.get("subtitle") or "")[:20],
                "kp_code": str(s.get("kp_code") or "") if str(s.get("kp_code") or "") in valid_codes else "",
                "key_points": [str(x)[:40] for x in (s.get("key_points") or [])][:3],
                "narration": str(s.get("narration") or "")[:120],
                "minutes": min(max(int(s.get("minutes") or 3), 2), 5),
            }
        )
    title = str(
        data.get("title") or (course.title if course else topic)
    )[:40] or (topic or course.title if course else "")[:40]
    return True, keep, title


def _fallback_outline(course: Course | None, slide_count: int, topic: str = "") -> list:
    """确定性兜底：第一页导入、最后一页小结，中间按章节/主题切页。"""
    if course is not None:
        chapters = (course.preprocess_result or {}).get("chapters") or []
        cards = (course.preprocess_result or {}).get("knowledge_cards") or []
    else:
        chapters = []
        cards = []
    mid = slide_count - 2
    slides = [{"order": 1, "title": "课堂导入", "subtitle": course.title if course else topic, "kp_code": "", "key_points": ["回顾旧知", "提出本节课问题", "明确学习目标"], "narration": "同学们好，今天我们一起来学习这一课。", "minutes": 2}]
    for i in range(mid):
        ch = chapters[i] if i < len(chapters) else {"title": (topic or f"知识点 {i + 1}"), "summary": ""}
        card = cards[i] if i < len(cards) else {}
        slides.append(
            {
                "order": i + 2,
                "title": str(ch.get("title") or f"知识点 {i + 1}")[:12],
                "subtitle": str(card.get("title") or "")[:20],
                "kp_code": "",
                "key_points": [str(card.get("title") or ch.get("title") or "本节要点")[:40], "公式与例题", "易错提醒"],
                "narration": str(ch.get("summary") or f"接下来我们学习{ch.get('title')}")[:120],
                "minutes": 3,
            }
        )
    slides.append(
        {
            "order": len(slides) + 1,
            "title": "课堂小结",
            "subtitle": "核心公式 + 课后行动",
            "kp_code": "",
            "key_points": ["本节课核心公式", "常见易错点", "课后练什么"],
            "narration": "我们来总结一下今天的内容，并布置课后练习。",
            "minutes": 2,
        }
    )
    return slides


async def _gen_slide_content(outline: dict, knowledge_cards: str) -> dict:
    """单页内容生成；失败返回确定性 blocks（text 版要点），保证课堂不空页。"""
    from app.providers.router import get_model_router
    from app.skills.smart_quiz.main import parse_quiz_json

    router_llm = get_model_router()
    try:
        result = await router_llm.chat(
            messages=[
                {
                    "role": "user",
                    "content": _MATH_CONTENT_PROMPT.format(
                        outline_json=outline, knowledge_cards=knowledge_cards[:1500]
                    ),
                }
            ],
            temperature=0.3,
            max_tokens=4000,
            request_id=f"classroom-slide-{uuid.uuid4().hex[:12]}",
            scene="classroom_slide",
        )
        data = parse_quiz_json(result.get("content", "")) or {}
        blocks = data.get("blocks") or []
        if blocks:
            return {
                "blocks": [
                    {
                        "kind": str(b.get("kind") or "text"),
                        **({k: str(b[k])[:400] for k in ("text", "latex", "question", "analysis", "answer") if b.get(k) is not None}),
                    }
                    for b in blocks
                ][:8],
                "narration": str(data.get("narration") or "")[:120],
            }
    except Exception as e:
        logger.warning("classroom_slide_llm_failed", error=str(e)[:200])
    # 确定性兜底：要点转 text 块
    return {
        "blocks": [
            {"kind": "text", "text": kp} for kp in (outline.get("key_points") or [])
        ]
        or [{"kind": "text", "text": outline.get("title") or "本节要点"}],
        "narration": outline.get("narration") or "",
    }


async def _run_generation(session_id: str) -> None:
    """后台生成任务（两段式；OpenMAIC 语义：topic 即可生成，course 为可选上下文）"""
    try:
        async with background_session_factory() as db:
            session = await db.get(ClassroomSession, uuid.UUID(session_id))
            if session is None:
                return

            # 可选课程上下文（OpenMAIC：不依赖课程预处理，有则增强，无则按主题生成）
            course = None
            if session.course_id is not None:
                course = await db.get(Course, session.course_id)
                if course is None or course.deleted_at:
                    session.status = "failed"
                    session.error = "课程不存在"
                    await db.commit()
                    return
                if course.status != COURSE_STATUS_READY:
                    session.status = "failed"
                    session.error = "课程预处理未完成，请稍后再试"
                    await db.commit()
                    return

            # kp 白名单表（只允许从高中数学知识点表选择）
            kp_rows = await db.execute(
                select(KnowledgePoint.code, KnowledgePoint.name)
            )
            kp_table = "\n".join(f"{code}: {name}" for code, name in kp_rows.all())
            cards = ((course.preprocess_result or {}) if course else {}).get("knowledge_cards") or []
            knowledge_cards = "\n".join(
                f"- {c.get('title')}: {c.get('content')}"
                for c in cards
                if c.get("title") or c.get("content")
            ) or "（无知识卡）"

            # Step1 大纲（OpenMAIC：无课程时以主题为纲直接生成）
            _, outlines, title = await _gen_outline(
                course,
                session.slide_count,
                session.mode,
                kp_table,
                knowledge_cards,
                topic=session.title if course is None else "",
            )
            session.status = "generating"
            session.outlines = outlines
            session.title = title
            session.engine = "math_classroom_v1"
            await db.commit()

            # Step2 逐页内容（串行，进度写回则每页一 commit）
            slides: list[dict] = []
            for outline in outlines:
                content = await _gen_slide_content(outline, knowledge_cards)
                slides.append(
                    {
                        "order": outline["order"],
                        "title": outline["title"],
                        "subtitle": outline.get("subtitle") or "",
                        "kp_code": outline.get("kp_code") or "",
                        "minutes": outline.get("minutes") or 3,
                        "blocks": content["blocks"],
                        "narration": content["narration"],
                        "key_points": outline.get("key_points") or [],
                    }
                )
                session.slides = list(slides)  # 新 list 触发 JSONB 变更检测（同引用不落库）
                await db.commit()

            session.status = "ready"
            session.generated_at = datetime.now(UTC)
            session.error = None
            await db.commit()
            logger.info(
                "classroom_session_ready", session_id=session_id, slides=len(slides)
            )
    except Exception as e:
        logger.error("classroom_generation_failed", session_id=session_id, error=str(e)[:300])
        try:
            async with background_session_factory() as db:
                s = await db.get(ClassroomSession, uuid.UUID(session_id))
                if s:
                    s.status = "failed"
                    s.error = str(e)[:300]
                    await db.commit()
        except Exception:
            pass


# ==================== 端点 ====================


@router.post("/sessions")
async def create_session(
    req: SessionCreateRequest,
    background: BackgroundTasks,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建 AI 数学课堂会话（OpenMAIC 语义：topic 即可；course_id 可选增强）"""

    course = None
    if req.course_id is not None:
        course = await db.get(Course, req.course_id)
        if course is None or course.deleted_at:
            return ApiResponse(code=40400, message="课程不存在", data=None)
        if course.status != COURSE_STATUS_READY:
            return ApiResponse(code=40901, message="课程预处理未完成，请稍后再试", data=None)

    # 无课程时以 topic 为标题（自由生成，对齐 OpenMAIC 首页输入即生成）
    session = ClassroomSession(
        course_id=req.course_id,
        user_id=uuid.UUID(user["sub"]),
        title=(course.title if course else (req.topic or "").strip())[:180] or "数学课堂",
        mode=req.mode,
        slide_count=req.slide_count,
        status="generating",
    )
    db.add(session)
    await db.commit()
    background.add_task(_run_generation, str(session.id))
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "session_id": str(session.id),
            "course_id": str(course.id) if course else None,
            "title": session.title,
            "slide_count": session.slide_count,
            "mode": session.mode,
            "status": "generating",
        },
    )


@router.get("/sessions")
async def list_sessions(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """我的课堂会话列表"""
    user_id = uuid.UUID(user["sub"])
    rows = await db.execute(
        select(ClassroomSession)
        .where(ClassroomSession.user_id == user_id)
        .order_by(ClassroomSession.created_at.desc())
        .limit(20)
    )
    items = [
        {
            "session_id": str(s.id),
            "course_id": str(s.course_id),
            "title": s.title,
            "mode": s.mode,
            "slide_count": s.slide_count,
            "status": s.status,
            "error": s.error,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in rows.scalars().all()
    ]
    return ApiResponse(code=0, message="ok", data={"total": len(items), "items": items})


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """会话详情（outlines + slides + 生成状态）"""
    session = await db.get(ClassroomSession, session_id)
    if session is None or str(session.user_id) != user["sub"]:
        return ApiResponse(code=40400, message="会话不存在", data=None)
    course = await db.get(Course, session.course_id)
    return ApiResponse(
        code=0,
        message="ok",
        data={
            "session_id": str(session.id),
            "course_id": str(session.course_id),
            "course_title": course.title if course else session.title,
            "title": session.title,
            "mode": session.mode,
            "slide_count": session.slide_count,
            "status": session.status,
            "engine": session.engine,
            "error": session.error,
            "outlines": session.outlines or [],
            "slides": session.slides or [],
            "generated_at": session.generated_at.isoformat() if session.generated_at else None,
            "created_at": session.created_at.isoformat() if session.created_at else None,
        },
    )