"""上下文装配（kernel/context.py）

总预算 12K token，P0~P2 保命段永不裁。裁剪顺序：P3→P5→P4→P6。
"""


class ContextAssembler:
    """上下文装配器"""

    # ADR-001-10: 12K 窗口预算（token）
    BUDGET = {
        "P0_system_persona": 800,
        "P1_user_message": 2000,
        "P2_skill_params": 600,
        "P3_rag_chunks": 4000,
        "P4_working_memory": 1600,
        "P5_user_profile": 500,
        "P6_episodic": 800,
        "P7_output_spec": 400,
    }

    async def assemble(self, decision: dict, ctx: dict) -> list[dict]:
        """装配上下文消息列表。

        TODO: 实现上下文装配逻辑
        """
        return []
