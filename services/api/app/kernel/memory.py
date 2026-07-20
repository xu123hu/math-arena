"""记忆管理（kernel/memory.py）

工作记忆 = 滚动摘要 + 最近 10 条消息。
"""

from dataclasses import dataclass, field


@dataclass
class WorkingMemory:
    """工作记忆"""

    summary: str = ""
    recent_messages: list[dict] = field(default_factory=list)


@dataclass
class UserProfile:
    """用户档案（M1 只读，M2 事件驱动写）"""

    grade: str = ""
    level: str = "unknown"
    weak_points: list[dict] = field(default_factory=list)
    preferences: dict = field(default_factory=dict)


class MemoryManager:
    """记忆管理器"""

    async def get_working_memory(self, conversation_id: str) -> WorkingMemory:
        """返回 {summary, recent_messages}：滚动摘要 + 最近 10 条原文。

        TODO: 实现记忆读取逻辑
        """
        return WorkingMemory()

    async def maybe_update_summary(self, conversation_id: str) -> None:
        """每 12 条消息触发一次摘要更新。

        异步执行（BackgroundTasks），失败只记日志。
        TODO: 实现摘要更新逻辑
        """
        pass

    async def get_user_profile(self, user_id: str) -> UserProfile:
        """获取用户档案。M1 只读不写。"""
        return UserProfile()
