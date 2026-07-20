"""RAG 管线（kernel/rag.py）

三路召回（向量 + 全文 + 知识点标签）→ RRF 融合 → Rerank → 拒答闸门。
"""
from dataclasses import dataclass, field


@dataclass
class ScoredChunk:
    """带分数的切片"""

    chunk_id: str
    doc_id: str
    content: str
    doc_title: str = ""
    score: float = 0.0


@dataclass
class RAGResult:
    """RAG 检索结果"""

    chunks: list[ScoredChunk] = field(default_factory=list)
    answerable: bool = True
    refuse_reason: str = ""


class RAGPipeline:
    """RAG 检索管线"""

    async def retrieve(self, question: str, ctx: dict) -> RAGResult:
        """标准 RAG 流程：
        1. 改写：星火指代补全，temperature=0
        2. 三路召回并行：pgvector + pg_trgm + kp_tags
        3. RRF 融合（k=60）取 top10
        4. bge-reranker 精排取 top4
        5. 拒答闸门：rerank 最高分 < 0.35 → answerable=False

        TODO: 实现完整 RAG 流程
        """
        return RAGResult()
