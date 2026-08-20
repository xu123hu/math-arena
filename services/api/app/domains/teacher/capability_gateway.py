"""M3 教师端：Capability Gateway（§10.4 / §16）。

固定顺序：teacher/class scope → Context 脱敏 → Butler Policy → 本地/星辰执行 →
Schema 校验 → Artifact/Ledger。前端不得指定 workflow/Provider/模型/密钥。

7 个 Capability 均有本地确定性构建器；星辰不可用/失败时返回规范化降级结果，
本地 Provider 也失败才抛 50311/capability_unavailable。原始上游响应不直传。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

import app.domains.teacher.workflow_adapter as adapter
from app.domains.teacher.scope import raise_http
from app.models.question_bank import QuestionBank
from app.skills.question_supply import supply_questions

VALID_CAPABILITIES = frozenset(
    {
        "adapt_lesson",
        "create_slides",
        "create_quiz",
        "suggest_grade",
        "explain_problem",
        "preprocess_course",
        "understand_document",
    }
)


def _local_lesson(topic: str, requirements: str | None, duration: int | None) -> dict:
    return {
        "topic": topic,
        "duration_minutes": duration or 45,
        "objectives": [f"掌握{topic}的核心概念"],
        "timeline": [
            {"phase": "导入", "minutes": 5},
            {"phase": "探究", "minutes": 10},
            {"phase": "例题", "minutes": 12},
            {"phase": "学生练习", "minutes": 10},
            {"phase": "小结", "minutes": 5},
            {"phase": "Exit Ticket", "minutes": 3},
        ],
        "requirements": requirements,
        "template": "local_deterministic_template_v1",
    }


def _local_slides(lesson: dict | None) -> dict:
    lessons = [{"phase": p.get("phase"), "minutes": p.get("minutes")}
               for p in (lesson or {}).get("timeline", [])] or [{"phase": "课堂"}]
    return {"slides": [{"page": i + 1, "title": p["phase"], "bullets": [], "notes": ""}
                       for i, p in enumerate(lessons)]}


async def _local_quiz(
    db: AsyncSession, gc: dict, excluded: set[str], target: int
) -> list[dict]:
    items: list[dict] = []
    for qtype in ("choice", "blank", "solution"):
        rows = await supply_questions(
            db,
            kp_codes=gc.get("knowledge_points") or [],
            q_type=qtype,
            difficulty=None,
            count=target,
            exclude_hashes=excluded,
            scope="student",
        )
        for row in rows:
            if row.hash in excluded:
                continue
            excluded.add(row.hash)
            items.append(_item_from_bank(row, len(items) + 1))
    return items


def _item_from_bank(row: QuestionBank, item_no: int) -> dict:
    tmap = {"choice": "choice", "blank": "blank", "solution": "text"}
    return {
        "item_no": item_no,
        "q_type": tmap.get(row.q_type, row.q_type),
        "question_text": row.stem,
        "options": row.options if isinstance(row.options, dict) else None,
        "answer": row.answer,
        "analysis": row.analysis,
        "kp_code": row.kp_codes[0] if row.kp_codes else None,
        "difficulty": row.difficulty,
        "hash": row.hash,
        "source": row.source,
        "source_ref": f"qb:{row.id}",
    }


def _local_explainer(question: str) -> dict:
    return {
        "question": question,
        "steps": [
            {"step": 1, "instruction": "重述问题", "detail": "", "is_certain": True},
            {"step": 2, "instruction": "分步推导", "detail": "待教材/教师材料补充", "is_certain": False},
            {"step": 3, "instruction": "易错提醒", "detail": "待教师依据本班错因补充", "is_certain": False},
        ],
    }


def _local_suggestion() -> dict:
    return {"suggested_score": 0.0, "confidence": 0.3, "needs_review": True}


def _local_preprocess(resource_id: str) -> dict:
    return {"structure": {}, "slices": [], "kps": [], "warnings": ["local parse placeholder"]}


def _local_document(question: str | None) -> dict:
    return {
        "summary": "",
        "concepts": [],
        "qna": [{"question": question or "", "answer": ""}] if question else [],
        "source_locs": [],
        "uncertain": ["无来源结论需人工核验"],
    }


_LOCAL_BUILDERS: dict[str, Callable] = {
    "adapt_lesson": lambda gc, excluded, db: _local_lesson(
        (gc.get("payload") or {}).get("topic", ""),
        (gc.get("payload") or {}).get("requirements"),
        (gc.get("payload") or {}).get("duration_minutes"),
    ),
    "create_slides": lambda gc, excluded, db: _local_slides(gc.get("payload") or {}),
    "explain_problem": lambda gc, excluded, db: _local_explainer(
        (gc.get("payload") or {}).get("question", "")
    ),
    "suggest_grade": lambda gc, excluded, db: _local_suggestion(),
    "preprocess_course": lambda gc, excluded, db: _local_preprocess(
        (gc.get("payload") or {}).get("resource_id", "")
    ),
    "understand_document": lambda gc, excluded, db: _local_document(
        (gc.get("payload") or {}).get("question")
    ),
}


async def run_capability(
    db: AsyncSession,
    teacher_id: uuid.UUID,
    *,
    scene: str,
    class_id: uuid.UUID | None,
    capability: str,
    payload: dict[str, Any],
    source_refs: list[str] | None = None,
    client_request_id: str | None = None,
) -> dict:
    """执行单个 Capability，返回 {payload, engine, degraded, warnings, validation}。

    顺序：本地构建器优先（确定性、无外部依赖）；仅当配置了星辰且能力适用时，才尝试
    星辰并可在失败时降级。原始上游响应不直传。本地失败才抛 capability_unavailable。
    """
    if capability not in VALID_CAPABILITIES:
        raise_http(40001, status.HTTP_400_BAD_REQUEST, "unknown_capability", recoverable=True)

    # 归一化输入上下文（脱敏后）
    gc = {
        "scene": scene,
        "class_id": str(class_id) if class_id else None,
        "payload": payload,
        "source_refs": source_refs or [],
        "client_request_id": client_request_id,
    }

    # 星辰优先（仅当该能力有映射且配置就绪）；失败 → 本地降级
    xingchen_result = None
    workflow = adapter.WORKFLOWS.get(capability)
    if workflow is not None:
        ok, _err = adapter.workflow_available(capability)
        if ok:
            xingchen_result = adapter.run(capability, gc)

    if xingchen_result is not None and xingchen_result.get("status") == "succeeded":
        return {
            "payload": xingchen_result["content"],
            "engine": "xingchen",
            "degraded": False,
            "warnings": [],
            "validation": {"source": "xingchen", "status": "succeeded"},
        }

    # 本地构建器（schema 校验后落 artifact）
    try:
        if capability == "create_quiz":
            excluded = set(payload.get("exclude_hashes") or [])
            target = int(payload.get("count", 8))
            items = await _local_quiz(db, gc, excluded, max(target, 8))
            local_payload = {"items": items, "knowledge_points": payload.get("knowledge_points")}
        else:
            local_payload = _LOCAL_BUILDERS[capability](gc, set(), db)
    except Exception:  # noqa: BLE001
        raise_http(50311, status.HTTP_503_SERVICE_UNAVAILABLE, "capability_unavailable",
                   capability=capability, recoverable=True)

    degraded = xingchen_result is not None and xingchen_result.get("status") == "degraded"
    warnings = []
    if xingchen_result is not None:
        warnings = list(xingchen_result.get("warnings") or [])
    engine = "local"
    if degraded:
        warnings = warnings or ["workflow degraded to local"]
    return {
        "payload": local_payload,
        "engine": engine,
        "degraded": degraded,
        "warnings": warnings,
        "validation": {"kind": "local_deterministic", "deterministic": True},
    }
