"""Skill 抽象基类（skills/base.py）

所有 skill 继承 SkillExecutor，通过 manifest 注册。
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any


class SkillExecutor(ABC):
    """Skill 执行器基类"""

    manifest: dict  # SkillManifest

    @abstractmethod
    async def run(self, params: dict, ctx: dict) -> AsyncIterator[dict]:
        """产出 SSE 事件序列。

        chat 兜底技能 yield token 事件；
        功能性 skill 通常 yield status(处理中) → token* → card* → 结束。

        禁止 yield meta/citation/badge/done —— 这四个由主链路统一发（§7.7）。
        """
        yield {}  # pragma: no cover
