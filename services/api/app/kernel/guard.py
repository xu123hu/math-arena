"""防护层（kernel/guard.py）

输入检查（长度/注入）+ 输出校验（citation/越权字段）。
"""
from dataclasses import dataclass


@dataclass
class GuardResult:
    """防护检查结果"""

    safe: bool = True
    cleaned_message: str = ""
    reason: str = ""


class Guard:
    """防护层"""

    async def check_input(self, message: str, ctx: dict) -> GuardResult:
        """输入检查：
        - 长度 > 4000 截断
        - 注入模式（'忽略以上指令'等）命中 → 清洗 + 日志
        - 敏感词拦截

        TODO: 实现输入防护逻辑
        """
        if len(message) > 4000:
            message = message[:4000]
        return GuardResult(safe=True, cleaned_message=message)

    async def check_output(self, text: str, ctx: dict) -> str:
        """输出校验：
        - citation chunk_id 必须 ∈ 本次召回集，否则删标记
        - 越权字段扫描（白名单）

        TODO: 实现输出防护逻辑
        """
        return text
