"""管家调度器（Butler Orchestrator）— M2 迭代17

职责（对齐方案 §2.2）：监听学习事件 → 决策（去重 + 反骚扰限额）→ 触发管家技能
→ 落库 ai_recommendations → 驱动前端数据变化。

纪律：dispatch 全程 best-effort，任何异常吞掉记日志，绝不向上抛、绝不阻塞主链路。

两种触发模式：
1. 事件驱动（dispatch）：判分/错题/登录等事件后异步处理；
2. 请求内同步（router 直调 skills）：今日计划/周报/路径规划等页面实时拉取。
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.butler import state
from app.config import settings
from app.models.ai_recommendation import AIRecommendation
from app.models.learning_event import LearningEvent

logger = structlog.get_logger(__name__)


class ButlerOrchestrator:
    """管家调度器（单例）"""

    async def dispatch(self, db: AsyncSession, event: LearningEvent) -> None:
        """处理一条学习事件（best-effort，绝不抛异常）。"""
        event_type = event.event_type
        user_id = event.user_id
        try:
            # 反骚扰：同类事件去重窗口
            if await state.event_seen_recently(user_id, event_type, settings.butler_dedup_hours):
                await self._finalize(db, event)
                return

            # 事件 → 技能映射
            if event_type in ("quiz_judge", "error_recorded", "mastery_changed", "error_reviewed"):
                # 学情变化：静默刷新画像（不主动打扰）
                await state.refresh_profile_from_mastery(db, user_id)
            elif event_type == "login":
                # 登录：仅在限额内生成主动开场白
                await self._proactive(db, user_id, event)

            await state.mark_event_seen(user_id, event_type)
            await self._finalize(db, event)
        except Exception as e:  # noqa: BLE001
            logger.info("butler_dispatch_fail", event_type=event_type, error=str(e)[:200])
            try:
                await self._finalize(db, event, status="failed")
            except Exception:  # noqa: BLE001
                pass

    async def _proactive(self, db: AsyncSession, user_id: uuid.UUID, event: LearningEvent) -> None:
        """登录事件：限额内生成主动开场白推荐。"""
        if not await state.incr_push_count(user_id, settings.butler_proactive_limit):
            return
        from app.butler.skills import proactive_greeting

        greeting = await proactive_greeting(db, user_id)
        db.add(
            AIRecommendation(
                user_id=user_id,
                kind="proactive_greeting",
                source="butler_proactive",
                payload={"text": greeting},
            )
        )

    async def _finalize(
        self, db: AsyncSession, event: LearningEvent, status: str = "processed"
    ) -> None:
        event.status = status
        event.retry_count = int(event.retry_count or 0) + (1 if status == "failed" else 0)
        if status == "processed":
            from datetime import UTC, datetime

            event.processed_at = datetime.now(UTC)


_orchestrator: ButlerOrchestrator | None = None


def get_orchestrator() -> ButlerOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ButlerOrchestrator()
    return _orchestrator
