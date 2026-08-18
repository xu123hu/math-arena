"""管家工具集（Tool Set）— 封装所有业务能力供 AI 调用（M2 迭代17）

每个工具是独立 async 函数，返回结构化 dict。orchestrator / skills 直接调用；
TOOL_SPECS + call_tool 暴露统一调度入口（为后续 Function Calling 预留）。

底层 100% 复用既有服务，不重写业务：
- 学情：services/growth.py（load_mastery_rows / load_errors_fsrs / composite_score / classify_subtype）
- 出题：skills/question_supply.py（supply_questions 题库真题优先）
- 组卷：skills/mock_exam.py（assemble_exam）
- 图谱：knowledge_points + kp_prerequisites
- 路由：services/platform_context.py（_PLATFORM_MAP / match_platform_item）
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.growth import KpPrerequisite
from app.models.knowledge_point import KnowledgePoint
from app.services import growth as growth_svc
from app.services.platform_context import match_platform_item

# 页面路由表：前端路由 key → 跳转指令（与平台地图对齐）
_ROUTE_HINTS: dict[str, dict] = {
    "errors": {"route": "/errors", "label": "错题本"},
    "practice": {"route": "/practice", "label": "练题中心"},
    "report": {"route": "/report", "label": "学情报告"},
    "graph": {"route": "/graph", "label": "知识图谱"},
    "exam": {"route": "/exam", "label": "模拟考试"},
    "tasks": {"route": "/tasks", "label": "每日任务"},
}


async def query_profile(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """学情查询：综合分 / 掌握度概览 / 薄弱点 Top / 错题统计。"""
    mastery_rows = await growth_svc.load_mastery_rows(db, user_id)
    error_views = await growth_svc.load_errors_fsrs(db, user_id)
    hint_dep = await growth_svc.hint_dependency(db, user_id)
    streak = await growth_svc.current_streak(db, user_id)

    avg_mastery = (
        sum(r["mastery"] for r in mastery_rows) / len(mastery_rows) if mastery_rows else 0.0
    )
    weak = sorted(mastery_rows, key=lambda r: r["mastery"])[:5]
    due_errors = [v for v in error_views if v["is_due"]]

    return {
        "composite_score": growth_svc.composite_score(avg_mastery, hint_dep, streak),
        "avg_mastery": round(avg_mastery, 4),
        "hint_dependency": round(hint_dep, 4),
        "streak_days": streak,
        "mastery_count": len(mastery_rows),
        "weak_points": [
            {
                "kp_code": w["kp_code"],
                "kp_name": w["kp_name"],
                "mastery": round(w["mastery"], 4),
            }
            for w in weak
        ],
        "error_total": len(error_views),
        "error_due": len(due_errors),
    }


async def query_due_errors(db: AsyncSession, user_id: uuid.UUID, limit: int = 10) -> list[dict]:
    """错题调度：FSRS 到期错题队列（按可提取性升序，最该先复习的在前）。"""
    error_views = await growth_svc.load_errors_fsrs(db, user_id)
    due = sorted((v for v in error_views if v["is_due"]), key=lambda v: v["retrievability"])
    return [
        {
            "record_id": str(v["record"].id),
            "kp_code": v["record"].kp_code,
            "retrievability": v["retrievability"],
            "level": v["level"],
            "hours_to_forget": v["hours_to_forget"],
        }
        for v in due[:limit]
    ]


async def query_weak_points(db: AsyncSession, user_id: uuid.UUID, limit: int = 4) -> list[dict]:
    """薄弱点排名：按掌握度升序（含练习量，避免"没练过"与"练了还差"混为一谈）。"""
    rows = sorted(
        await growth_svc.load_mastery_rows(db, user_id), key=lambda r: r["mastery"]
    )
    return [
        {
            "kp_code": r["kp_code"],
            "kp_name": r["kp_name"],
            "mastery": round(r["mastery"], 4),
            "practice_count": r["practice_count"],
            "correct_count": r["correct_count"],
        }
        for r in rows[:limit]
    ]


async def query_kp_deps(db: AsyncSession, kp_code: str) -> dict:
    """知识图谱：查询某知识点的前置依赖链（ALEKS precedence relation）。"""
    rs = await db.execute(select(KpPrerequisite).where(KpPrerequisite.kp_code == kp_code))
    prereqs = [r.prereq_code for r in rs.scalars().all()]
    kp = await db.execute(select(KnowledgePoint).where(KnowledgePoint.code == kp_code))
    kp_row = kp.scalar_one_or_none()
    return {
        "kp_code": kp_code,
        "kp_name": kp_row.name if kp_row else kp_code,
        "prereqs": prereqs,
    }


async def supply_variants(
    db: AsyncSession,
    user_id: uuid.UUID,
    kp_code: str,
    difficulties: tuple[str, ...] = ("easy", "medium", "hard"),
) -> list[dict]:
    """同类变式题：按知识点 + 难度递进供题（题库真题优先，复用 question_supply）。

    注：AI 生成变式走 smart_quiz（对话流），此处为题库确定性兜底。
    """
    from app.skills.question_supply import supply_questions

    out: list[dict] = []
    seen: set[str] = set()
    for diff in difficulties:
        rows = await supply_questions(
            db, kp_codes=[kp_code], q_type=None, difficulty=diff, count=1, exclude_hashes=seen
        )
        for row in rows:
            seen.add(row.hash)
            out.append(
                {
                    "hash": row.hash,
                    "q_type": row.q_type,
                    "stem": row.stem[:200],
                    "difficulty": row.difficulty,
                    "kp_codes": row.kp_codes,
                    "source": row.source,
                }
            )
    return out


def build_route(action: str) -> dict:
    """页面路由：生成前端跳转指令（支持对话内跳转）。"""
    hint = _ROUTE_HINTS.get(action)
    if hint:
        return {"type": "route", "route": hint["route"], "label": hint["label"]}
    # 回退平台地图意图匹配（动作词 + 功能名）
    matched = match_platform_item(action)
    if matched:
        return {"type": "route", "route": matched.get("route"), "label": matched.get("label")}
    return {"type": "route", "route": None, "label": action}


async def recommend_path(db: AsyncSession, user_id: uuid.UUID, top_n: int = 3) -> list[dict]:
    """学习路径推荐（规则骨架）：薄弱点 TopN → 查前置依赖 → 生成阶梯学习顺序。

    LLM 只做文案润色，前置依赖正确性由规则保证（对齐方案 §4.5）。
    """
    weak = await query_weak_points(db, user_id, limit=top_n)
    path: list[dict] = []
    for w in weak:
        deps = await query_kp_deps(db, w["kp_code"])
        path.append(
            {
                "kp_code": w["kp_code"],
                "kp_name": w["kp_name"],
                "mastery": w["mastery"],
                "prereqs": deps["prereqs"],
                "type": "专练",
            }
        )
    return path


# ==================== 统一调度入口 ====================

TOOL_SPECS: list[dict] = [
    {"name": "query_profile", "description": "查询学生综合分、掌握度、薄弱点、错题统计", "params": []},
    {"name": "query_due_errors", "description": "查询 FSRS 到期错题队列", "params": ["limit"]},
    {"name": "query_weak_points", "description": "查询薄弱知识点排名", "params": ["limit"]},
    {"name": "query_kp_deps", "description": "查询知识点前置依赖链", "params": ["kp_code"]},
    {"name": "supply_variants", "description": "按知识点/难度生成同类变式题", "params": ["kp_code", "difficulties"]},
    {"name": "build_route", "description": "生成前端页面跳转指令", "params": ["action"]},
    {"name": "recommend_path", "description": "基于掌握度推荐学习路径", "params": ["top_n"]},
]

_TOOL_FUNCS = {
    "query_profile": query_profile,
    "query_due_errors": query_due_errors,
    "query_weak_points": query_weak_points,
    "query_kp_deps": query_kp_deps,
    "supply_variants": supply_variants,
    "build_route": build_route,
    "recommend_path": recommend_path,
}


async def call_tool(name: str, db: AsyncSession, user_id: uuid.UUID, params: dict | None = None) -> dict:
    """按名称调度工具（供 orchestrator / 未来 Function Calling 使用）。"""
    params = params or {}
    fn = _TOOL_FUNCS.get(name)
    if fn is None:
        return {"error": f"未知工具: {name}"}
    try:
        if name == "build_route":
            return fn(params.get("action", ""))
        if name == "query_kp_deps":
            return await fn(db, params.get("kp_code", ""))
        if name == "supply_variants":
            return await fn(db, user_id, params.get("kp_code", ""), params.get("difficulties", ("easy", "medium", "hard")))
        if name == "recommend_path":
            return await fn(db, user_id, params.get("top_n", 3))
        if name == "query_due_errors":
            return await fn(db, user_id, params.get("limit", 10))
        if name == "query_weak_points":
            return await fn(db, user_id, params.get("limit", 4))
        return await fn(db, user_id)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200]}
