"""题库供给层（题库优先：真题检索 → AI 生成只补缺口）

供给规则：
- 按 kp_codes 数组重叠（GIN）+ q_type + difficulty 过滤，ORDER BY random() 随机取；
- 指定难度供不满时可放宽难度再补（题型与知识点不放宽——刷偏知识点比刷偏难度危害大）；
- exclude_hashes 排除本次已选题（同卷/同题组内不重复出题）；
- kp 粒度对齐：expand_kp_codes 将章节码/小节码双向展开（父码展开子码、子码回溯父码），
  题库标注粒度与 knowledge_points 树粒度不一致时仍能命中。

日限口径（daily_ai_used）：只计 AI 生成题，题库真题不占额度——
作答计题（非试卷提交明细中对应 AI 题）+ 组卷计题（exam:* 今日成卷的 AI 题，生成即计）。
practice/start 与 exam/generate 共用本实现，双端口径一致。
"""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coursework import Quiz, QuizItem, Submission, SubmissionItem
from app.models.knowledge_point import KnowledgePoint
from app.models.question_bank import QuestionBank

logger = structlog.get_logger(__name__)


async def expand_kp_codes(db: AsyncSession, codes: list[str]) -> list[str]:
    """kp code 双向粒度展开：自身 + 父码 + 直接子码（章节码 ↔ 小节码对齐题库标注粒度）"""
    uniq = [c for c in dict.fromkeys(codes) if c]
    if not uniq:
        return []
    rows = (
        await db.execute(select(KnowledgePoint.id, KnowledgePoint.code, KnowledgePoint.parent_id))
    ).all()
    code_by_id = {r.id: r.code for r in rows}
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}
    for r in rows:
        if r.parent_id is not None and r.parent_id in code_by_id:
            parent_of[r.code] = code_by_id[r.parent_id]
            children_of.setdefault(code_by_id[r.parent_id], []).append(r.code)
    expanded: set[str] = set(uniq)
    for c in uniq:
        if c in parent_of:
            expanded.add(parent_of[c])
        expanded.update(children_of.get(c, []))
    return sorted(expanded)


async def supply_questions(
    db: AsyncSession,
    *,
    kp_codes: list[str],
    q_type: str | None = None,
    difficulty: str | None = None,
    count: int,
    exclude_hashes: set[str] | None = None,
    scope: str = "student",
) -> list[QuestionBank]:
    """从题库随机供题：kp 数组重叠 + 题型/难度过滤；难度不足放宽再补；如实际命中数返回

    返回的 QuestionBank 即题库原题（is_real_exam 真题标记随行），调用方转为 QuizItem 时
    ai_generated=False、source 透传真题来源。

    scope 过滤（迭代09+ 题库治理）：只供指定端可见题（默认 student），
    并排除竞赛/超纲标记题——防止 TAL 竞赛题等 research 端素材供给学生。
    """
    if count <= 0 or not kp_codes:
        return []
    codes = await expand_kp_codes(db, kp_codes)
    excluded = set(exclude_hashes or set())

    async def _query(diff: str | None, limit: int, extra: set[str]) -> list[QuestionBank]:
        if limit <= 0:
            return []
        stmt = (
            select(QuestionBank)
            .where(
                QuestionBank.deleted_at.is_(None),
                QuestionBank.kp_codes.overlap(codes),
                QuestionBank.scope == scope,
                QuestionBank.is_competition.is_(False),
                QuestionBank.out_of_syllabus.is_(False),
            )
            .order_by(func.random())
            .limit(limit)
        )
        if q_type:
            stmt = stmt.where(QuestionBank.q_type == q_type)
        if diff:
            stmt = stmt.where(QuestionBank.difficulty == diff)
        hashes = excluded | extra
        if hashes:
            stmt = stmt.where(QuestionBank.hash.not_in(hashes))
        return list((await db.execute(stmt)).scalars().all())

    picked = await _query(difficulty, count, set())
    if difficulty and len(picked) < count:
        # 难度放宽补缺口（kp/题型不放宽）；已选题不再重复
        picked.extend(await _query(None, count - len(picked), {p.hash for p in picked}))
    return picked


def quiz_item_from_bank(
    row: QuestionBank,
    *,
    quiz_id: uuid.UUID,
    item_no: int,
    kp_code: str | None = None,
) -> QuizItem:
    """题库行 → QuizItem（ai_generated=False；source 真题来源透传；source_chunk_id 留 qb: 溯源引用）

    kp_code 缺省取题库行首个标注码；组卷场景传槽位 kp（掌握度回填与排布计划对齐）。
    """
    return QuizItem(
        quiz_id=quiz_id,
        item_no=item_no,
        q_type=row.q_type,
        question_text=row.stem,
        options=row.options if isinstance(row.options, dict) else None,
        answer=row.answer,
        answer_analysis=row.analysis,
        kp_code=kp_code or (row.kp_codes[0] if row.kp_codes else None),
        difficulty=row.difficulty,
        ai_generated=False,
        source=row.source,
        source_chunk_id=f"qb:{row.id}",
        image=row.image or [],
    )


async def daily_ai_used(db: AsyncSession, user_id: uuid.UUID) -> int:
    """今日 AI 生成题已用量（日限唯一口径：只计 AI 题，题库真题不占额度）

    两路合并（沿用存量口径，仅追加 ai_generated 过滤）：
    - 作答计题：今日非试卷提交明细中对应 AI 题；无法溯源的明细（QuizItem 缺失/对话临时题）
      按 AI 计（保守口径，防漏计）；
    - 组卷计题：今日成卷（exam:*）中的 AI 题（生成即计，其后试卷作答不再重复计）。
    当日口径与存量一致：服务器本地日期零点。
    """
    today_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    sub_count = (
        await db.execute(
            select(func.count())
            .select_from(SubmissionItem)
            .join(Submission, SubmissionItem.submission_id == Submission.id)
            .outerjoin(Quiz, Submission.quiz_id == Quiz.id)
            .outerjoin(
                QuizItem,
                (QuizItem.quiz_id == Submission.quiz_id)
                & (QuizItem.item_no == SubmissionItem.item_no),
            )
            .where(
                Submission.user_id == user_id,
                SubmissionItem.created_at >= today_start,
                # 排除试卷提交（试卷 AI 题已在组卷时计入，防双计）
                (Quiz.id.is_(None)) | (~Quiz.source.like("exam:%")),
                # 题库题（ai_generated=False）不计；无法溯源的按 AI 计
                (QuizItem.id.is_(None)) | (QuizItem.ai_generated.is_(True)),
            )
        )
    ).scalar() or 0
    exam_count = (
        await db.execute(
            select(func.count())
            .select_from(QuizItem)
            .join(Quiz, QuizItem.quiz_id == Quiz.id)
            .where(
                Quiz.user_id == user_id,
                Quiz.source.like("exam:%"),
                Quiz.deleted_at.is_(None),
                QuizItem.deleted_at.is_(None),
                QuizItem.ai_generated.is_(True),
                QuizItem.created_at >= today_start,
            )
        )
    ).scalar() or 0
    return int(sub_count) + int(exam_count)
