"""M3 教师端：班级可行动洞察（§11 真数据聚合）。

洞察数据一律来自确定性 SQL 聚合（提交率变化/错误集中/低掌握度/待复核/备课缺口），
不编造 evidence；LLM 只允许润色 summary/recommended_actions 文案。
默认不返回学生逐人敏感明细，只返回聚合证据。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.class_member import ClassMember
from app.models.coursework import Assignment, MasteryRecord, Submission, SubmissionItem
from app.models.teacher import ActionableInsight

MAX_INSIGHTS = 3


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _serialize(ins: ActionableInsight) -> dict:
    """对齐前端 ActionableInsight 契约（evidence 摘要为字符串，动作为标签数组）。"""
    evidence = ins.evidence or {}
    evidence_text = "；".join(
        f"{k}={v}" for k, v in evidence.items() if not isinstance(v, (dict, list))
    ) or "见数据窗口内聚合"
    actions = [
        (a.get("label") or a.get("action") or str(a)) if isinstance(a, dict) else str(a)
        for a in (ins.recommended_actions or [])
    ]
    return {
        "insight_id": str(ins.id),
        "kind": ins.kind,
        "summary": ins.summary,
        "evidence": evidence_text,
        "data_window": {
            "from": ins.window_start.isoformat() if ins.window_start else "",
            "to": ins.window_end.isoformat() if ins.window_end else "",
        },
        "recommended_actions": actions,
        "confidence": float(ins.confidence or 0.0),
        "applied": ins.status == "applied",
    }


async def _review_backlog(db, class_id: uuid.UUID) -> ActionableInsight | None:
    # 待复核批改：该班提交的 needs_review 或 pending_review 作答数
    sub_ids = select(Submission.id).join(
        Assignment, Assignment.id == Submission.assignment_id
    ).where(Assignment.class_id == class_id)
    cnt = await db.scalar(
        select(func.count(SubmissionItem.id)).where(
            SubmissionItem.submission_id.in_(sub_ids),
            (
                (SubmissionItem.needs_review.is_(True))
                | (SubmissionItem.verdict == "pending_review")
            ),
        )
    )
    if not cnt:
        return None
    return ActionableInsight(
        class_id=class_id,
        kind="review_backlog",
        summary=f"待复核批改 {cnt} 份，建议按题集中确认",
        evidence={"count": int(cnt)},
        recommended_actions=[{"action": "open_grading", "label": "开始批改"}],
        confidence=0.9,
        window_end=_now_utc(),
    )


async def _low_mastery(db, class_id: uuid.UUID) -> ActionableInsight | None:
    # 低掌握度群体比例：该班学生成员中，平均掌握度 < 0.5 的人数占比（确定性聚合）
    student_ids = select(ClassMember.user_id).where(
        ClassMember.class_id == class_id,
        ClassMember.member_role == "student",
        ClassMember.confirmed.is_(True),
    )
    rows = (
        await db.execute(
            select(MasteryRecord.user_id, func.avg(MasteryRecord.mastery).label("m"))
            .where(MasteryRecord.user_id.in_(student_ids))
            .group_by(MasteryRecord.user_id)
        )
    ).all()
    low = [r for r in rows if (r[1] or 0) < 0.5]
    total = len(rows)
    if not total or len(low) / total < 0.2:
        return None
    return ActionableInsight(
        class_id=class_id,
        kind="low_mastery",
        summary=f"约 {int(len(low) / total * 100)}% 学生当前掌握度偏低",
        evidence={"total": total, "low_count": len(low), "ratio": round(len(low) / total, 2)},
        recommended_actions=[{"action": "open_class_detail", "label": "查看班级"}],
        confidence=0.75,
        window_end=_now_utc(),
    )


async def _submission_trend(db, class_id: uuid.UUID) -> ActionableInsight | None:
    # 提交率变化：比较最近两个已发布作业的提交数（确定性聚合）
    recent = (
        await db.execute(
            select(Assignment.id, Assignment.title, Assignment.created_at)
            .where(Assignment.class_id == class_id, Assignment.status.in_(("published", "closed")))
            .order_by(Assignment.created_at.desc())
            .limit(2)
        )
    ).all()
    if len(recent) < 2:
        return None
    counts = []
    for a in recent:
        c = await db.scalar(
            select(func.count(Submission.id)).where(
                Submission.assignment_id == a[0], Submission.deleted_at.is_(None)
            )
        )
        counts.append(int(c or 0))
    if counts[0] == counts[1]:
        return None
    sign = "上升" if counts[0] > counts[1] else "下降"
    return ActionableInsight(
        class_id=class_id,
        kind="submission_trend",
        summary=f"较上份作业，最近作业提交量{sign}（{counts[1]} → {counts[0]}）",
        evidence={"recent_count": counts[0], "previous_count": counts[1]},
        recommended_actions=[{"action": "open_assignment", "label": "查看作业"}],
        confidence=0.8,
        window_start=recent[1][2],
        window_end=recent[0][2],
    )


async def compute_class_insights(
    db: AsyncSession, teacher_id: uuid.UUID, class_id: uuid.UUID, *, actionable: bool = True
) -> list[dict]:
    """聚合该班洞察，最多 MAX_INSIGHTS 条；优先取已持久化 active 洞察，其次现算。"""
    from app.domains.teacher.scope import assert_teacher_in_class

    await assert_teacher_in_class(db, teacher_id, class_id)

    stored = (
        (
            await db.execute(
                select(ActionableInsight)
                .where(
                    ActionableInsight.class_id == class_id,
                    ActionableInsight.status == "active",
                )
                .order_by(ActionableInsight.confidence.desc())
                .limit(MAX_INSIGHTS)
            )
        )
        .scalars()
        .all()
    )
    if stored:
        return [_serialize(i) for i in stored]

    candidates = []
    for fn in (_submission_trend, _low_mastery, _review_backlog):
        ins = await fn(db, class_id)
        if ins is not None:
            candidates.append(ins)
    if not candidates:
        return []

    candidates.sort(key=lambda i: i.confidence, reverse=True)
    top = candidates[:MAX_INSIGHTS]
    db.add_all(top)
    await db.flush()
    for i in top:  # 触发主键生成后再序列化
        await db.refresh(i)
    return [_serialize(i) for i in top]
