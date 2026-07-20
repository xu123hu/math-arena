"""意图路由（kernel/router.py）

三路信号合并：L0 正则 → L2 Function Calling → L3 置信度闸门。
"""
from dataclasses import dataclass


@dataclass
class RouteDecision:
    """路由决策结果"""

    skill_id: str  # 命中的 skill，"chat" 为兜底
    confidence: float  # 0~1
    params: dict  # Function Calling 抽出的参数
    need_clarify: bool  # True 时主链路转澄清分支
    clarify_question: str = ""


async def route(message: str, ctx: dict) -> RouteDecision:
    """意图路由主函数

    三路信号按优先级合并：
    1. L0 前置信号（<5ms）：slash 命令、附件类型、surface 上下文
    2. L2 星火 Function Calling：skills manifest → functions 声明
    3. L3 置信度闸门：≥0.75 直接执行，0.4~0.75 低置信，<0.4 澄清

    TODO: 实现完整路由逻辑
    """
    # 暂时默认走 chat 兜底
    return RouteDecision(
        skill_id="chat",
        confidence=0.5,
        params={"question": message},
        need_clarify=False,
    )
