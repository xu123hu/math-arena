"""RAG 管线（kernel/rag.py）

三路召回（向量 + 全文 + 知识点标签）→ RRF 融合 → Rerank → 拒答闸门。
降级策略：Embedding 不可用跳过向量路；Reranker 不可用用 RRF 排序 + 原始分闸门。
拒答闸门分源判定（修复分度失配）：
- reranker 生效 → 用 rerank 分（0~1）对 settings.rag_refuse_threshold
- 降级路径 → 用 top 原始相关分 raw_score 对 settings.rag_raw_threshold
"""

import asyncio
import time
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.chunk import Chunk
from app.models.database import async_session_factory
from app.models.knowledge_point import KnowledgePoint
from app.providers.router import get_model_router

logger = structlog.get_logger()

# RRF 融合参数
RRF_K = 60
# 各路召回数量
RECALL_TOP_K = 20
# 融合后取 top
FUSED_TOP_K = 10
# 精排后取 top
RERANK_TOP_K = 4
# Embedding 可用性缓存 TTL（避免每查询一次健康检查往返）
EMBEDDING_HEALTH_TTL_S = 60.0
# Reranker 可用性缓存 TTL（避免每查询一次健康检查 HTTP 往返，~50-200ms）
RERANK_HEALTH_TTL_S = 60.0
_rerank_health_cache: dict = {"ok": False, "ts": 0.0}

REWRITE_PROMPT = """\
请将以下多轮对话中的最新问题改写为一个独立的、完整的问题。
要求：补全指代（"它"、"这个"、"那第3个"等），使问题脱离上下文也能理解。
只输出改写后的问题，不要解释。

对话历史：
{history}

最新问题：{question}

改写后的问题："""


@dataclass
class ScoredChunk:
    """带分数的切片"""

    chunk_id: str
    doc_id: str
    content: str
    doc_title: str = ""
    score: float = 0.0  # 排序分（RRF 分或 rerank 分）
    raw_score: float = 0.0  # 召回路原始相关分（wsim/cosine/kp），拒答闸门用
    kp_ids: list[str] = field(default_factory=list)


@dataclass
class RAGResult:
    """RAG 检索结果"""

    chunks: list[ScoredChunk] = field(default_factory=list)
    answerable: bool = True
    refuse_reason: str = ""
    rewritten_query: str = ""


class RAGPipeline:
    """RAG 检索管线"""

    def __init__(self) -> None:
        self._embedding_ok: bool = False
        self._embedding_checked_at: float = 0.0

    async def retrieve(
        self,
        question: str,
        *,
        db: AsyncSession,
        conversation_history: list[dict] | None = None,
        conversation_id: str = "",
        request_id: str = "",
    ) -> RAGResult:
        """标准 RAG 流程：
        1. 改写：LLM 指代补全，temperature=0
        2. 三路召回并行：pgvector + pg_trgm(word_similarity) + kp_tags
        3. RRF 融合（k=60）取 top10
        4. bge-reranker 精排取 top4（降级：RRF 排序直取）
        5. 拒答闸门（分源判定，见模块 docstring）
        """
        log = logger.bind(request_id=request_id)

        # Step 1: 查询改写（指代补全，串行 —— 评估后决定不做并行化，详见优化文档）
        rewritten = await self._rewrite_query(
            question,
            conversation_history or [],
            conversation_id=conversation_id,
            db=db,
            request_id=request_id,
        )
        log.info("rag.rewritten", original=question[:50], rewritten=rewritten[:50])

        # Step 2: 三路并行召回（每路独立 session，避免共享 AsyncSession 并发不安全）
        async def _run_vector_search():
            async with async_session_factory() as session:
                return await self._vector_search(rewritten, session)

        async def _run_trgm_search():
            async with async_session_factory() as session:
                return await self._trgm_search(rewritten, session)

        async def _run_kp_search():
            async with async_session_factory() as session:
                return await self._kp_tag_search(rewritten, session)

        vec_task = asyncio.create_task(_run_vector_search())
        trgm_task = asyncio.create_task(_run_trgm_search())
        kp_task = asyncio.create_task(_run_kp_search())

        vec_results, trgm_results, kp_results = await asyncio.gather(
            vec_task, trgm_task, kp_task, return_exceptions=True
        )

        # 处理异常（某路失败不影响其他路）
        if isinstance(vec_results, Exception):
            log.warning("rag.vector_failed", error=str(vec_results)[:100])
            vec_results = []
        if isinstance(trgm_results, Exception):
            log.warning("rag.trgm_failed", error=str(trgm_results)[:100])
            trgm_results = []
        if isinstance(kp_results, Exception):
            log.warning("rag.kp_failed", error=str(kp_results)[:100])
            kp_results = []

        log.info(
            "rag.recall",
            vec_count=len(vec_results),
            trgm_count=len(trgm_results),
            kp_count=len(kp_results),
        )

        # 如果三路都为空，直接返回不可答
        if not vec_results and not trgm_results and not kp_results:
            return RAGResult(
                chunks=[], answerable=False, refuse_reason="no_knowledge", rewritten_query=rewritten
            )

        # Step 3: RRF 融合
        fused = self._rrf_fuse([vec_results, trgm_results, kp_results], k=RRF_K)[:FUSED_TOP_K]

        # Step 4: Rerank（降级：RRF 排序直取）
        reranked, used_reranker = await self._rerank(rewritten, fused, request_id=request_id)
        final_chunks = reranked[:RERANK_TOP_K]

        # Step 5: 拒答闸门（分源判定）
        if not final_chunks:
            return RAGResult(
                chunks=[], answerable=False, refuse_reason="no_knowledge", rewritten_query=rewritten
            )
        if used_reranker:
            relevant = final_chunks[0].score >= settings.rag_refuse_threshold
            gate_score = final_chunks[0].score
        else:
            relevant = final_chunks[0].raw_score >= settings.rag_raw_threshold
            gate_score = final_chunks[0].raw_score
        if not relevant:
            log.info("rag.refused", gate_score=gate_score, used_reranker=used_reranker)
            return RAGResult(
                chunks=[],
                answerable=False,
                refuse_reason="low_relevance",
                rewritten_query=rewritten,
            )

        log.info("rag.success", chunks=len(final_chunks), gate_score=gate_score)
        return RAGResult(chunks=final_chunks, answerable=True, rewritten_query=rewritten)

    async def _rewrite_query(
        self,
        question: str,
        history: list[dict],
        *,
        request_id: str = "",
        conversation_id: str = "",
        db: AsyncSession | None = None,
    ) -> str:
        """查询改写：指代补全（读取对话滚动摘要 + 最近 4 条历史）"""
        # 无历史且无对话摘要时直接返回原问题
        if not history and not conversation_id:
            return question

        # 取最近 4 条历史用于改写
        recent = history[-4:] if history else []
        history_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content'][:100]}" for m in recent
        )

        # 读取对话摘要（如果有）
        summary_text = ""
        if conversation_id and db:
            try:
                from app.models.conversation import Conversation

                conv_result = await db.execute(
                    select(Conversation.summary).where(Conversation.id == conversation_id)
                )
                summary_text = conv_result.scalar() or ""
            except Exception:
                pass  # 摘要读取失败不影响改写

        # 动态构建改写 prompt（含摘要上下文）
        prompt_parts = ["请将以下多轮对话中的最新问题改写为一个独立的、完整的问题。"]
        prompt_parts.append("要求：补全指代（\"它\"、\"这个\"、\"那第3个\"等），使问题脱离上下文也能理解。")
        prompt_parts.append("只输出改写后的问题，不要解释。")
        if summary_text:
            prompt_parts.append(f"\n对话摘要：\n{summary_text[:500]}")
        if history_text:
            prompt_parts.append(f"\n对话历史：\n{history_text}")
        prompt_parts.append(f"\n最新问题：{question}")
        prompt_parts.append("\n改写后的问题：")
        prompt = "\n".join(prompt_parts)

        try:
            router = get_model_router()
            result = await router.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
                request_id=request_id,
                scene="rag_rewrite",
            )
            rewritten = result["content"].strip()
            return rewritten if rewritten else question
        except Exception as e:
            logger.warning("rag.rewrite_failed", error=str(e)[:100])
            return question

    async def _embedding_available(self) -> bool:
        """Embedding 服务可用性（60s 缓存，避免每查询一次健康检查往返）"""
        now = time.monotonic()
        if now - self._embedding_checked_at < EMBEDDING_HEALTH_TTL_S:
            return self._embedding_ok
        try:
            from app.providers.embedding import EmbeddingProvider

            health = await EmbeddingProvider().health_check()
            self._embedding_ok = bool(health.get("ok"))
        except Exception:
            self._embedding_ok = False
        self._embedding_checked_at = now
        return self._embedding_ok

    async def _vector_search(self, query: str, db: AsyncSession) -> list[ScoredChunk]:
        """向量路召回（pgvector cosine）

        降级：Embedding 服务不可用，返回空列表。
        """
        if not await self._embedding_available():
            return []

        try:
            from app.providers.embedding import EmbeddingProvider

            vectors = await EmbeddingProvider().embed([query])
            if not vectors or not vectors[0]:
                return []

            query_vec = vectors[0]
            distance = Chunk.embedding.cosine_distance(query_vec).label("dist")
            result = await db.execute(
                select(Chunk, distance)
                .where(Chunk.deleted_at.is_(None), Chunk.embedding.isnot(None))
                .order_by(distance)
                .limit(RECALL_TOP_K)
            )
            return [
                self._to_scored_chunk(
                    chunk,
                    default_score=1.0 - float(dist),
                    raw_score=1.0 - float(dist),
                )
                for chunk, dist in result.all()
            ]
        except Exception as e:
            logger.warning("rag.vector_error", error=str(e)[:200])
            return []

    async def _trgm_search(self, query: str, db: AsyncSession) -> list[ScoredChunk]:
        """全文路召回（pg_trgm word_similarity）

        短查询 vs 长文档必须用 word_similarity（similarity 在此场景
        得分量级过低，会被默认阈值全部过滤 —— M1 审查实测证实）。
        """
        try:
            result = await db.execute(
                text("""
                    SELECT c.id, c.doc_id, c.content, c.kp_ids,
                           word_similarity(:query, c.content) as wsim,
                           COALESCE(d.title, '教材') as doc_title
                    FROM chunks c
                    LEFT JOIN knowledge_docs d ON c.doc_id = d.id
                    WHERE c.deleted_at IS NULL
                      AND word_similarity(:query, c.content) > :threshold
                    ORDER BY wsim DESC
                    LIMIT :limit
                """),
                {"query": query, "threshold": settings.rag_trgm_threshold, "limit": RECALL_TOP_K},
            )
            rows = result.fetchall()
            return [
                ScoredChunk(
                    chunk_id=str(row[0]),
                    doc_id=str(row[1]),
                    content=row[2],
                    kp_ids=row[3] if row[3] else [],
                    score=float(row[4]),
                    raw_score=float(row[4]),
                    doc_title=row[5],
                )
                for row in rows
            ]
        except Exception as e:
            logger.warning("rag.trgm_error", error=str(e)[:200])
            # 降级：使用 ILIKE 模糊搜索
            return await self._fallback_text_search(query, db)

    async def _fallback_text_search(self, query: str, db: AsyncSession) -> list[ScoredChunk]:
        """降级文本搜索（当 pg_trgm 不可用时）：查询前缀 ILIKE"""
        result = await db.execute(
            select(Chunk)
            .where(
                Chunk.deleted_at.is_(None),
                Chunk.content.ilike(f"%{query[:20]}%"),
            )
            .limit(RECALL_TOP_K)
        )
        chunks = result.scalars().all()
        return [self._to_scored_chunk(c, 0.5, raw_score=0.5) for c in chunks]

    async def _kp_tag_search(self, query: str, db: AsyncSession) -> list[ScoredChunk]:
        """知识点标签路召回：查询文本包含知识点别名即命中"""
        try:
            alias_hit = text(
                "EXISTS (SELECT 1 FROM unnest(aliases) AS a " "WHERE :query ILIKE '%' || a || '%')"
            ).bindparams(query=query)
            kp_result = await db.execute(select(KnowledgePoint).where(alias_hit).limit(5))
            matched_kps = kp_result.scalars().all()

            if not matched_kps:
                return []

            # 通过 kp_ids 找关联的 chunks
            kp_ids = [str(kp.id) for kp in matched_kps]
            chunk_result = await db.execute(
                select(Chunk)
                .where(
                    Chunk.deleted_at.is_(None),
                    Chunk.kp_ids.overlap(kp_ids),
                )
                .limit(RECALL_TOP_K)
            )
            chunks = chunk_result.scalars().all()
            return [self._to_scored_chunk(c, 0.7, raw_score=0.7) for c in chunks]
        except Exception as e:
            logger.warning("rag.kp_error", error=str(e)[:200])
            return []

    def _rrf_fuse(self, result_lists: list[list[ScoredChunk]], k: int = 60) -> list[ScoredChunk]:
        """RRF（Reciprocal Rank Fusion）融合多路召回结果。

        score = RRF 分（排序用）；raw_score = 各路原始相关分的最大值（闸门用）。
        """
        scores: dict[str, float] = {}
        raw_scores: dict[str, float] = {}
        chunk_map: dict[str, ScoredChunk] = {}

        for results in result_lists:
            for rank, chunk in enumerate(results):
                rrf_score = 1.0 / (k + rank + 1)
                raw_scores[chunk.chunk_id] = max(
                    raw_scores.get(chunk.chunk_id, 0.0), chunk.raw_score
                )
                if chunk.chunk_id in scores:
                    scores[chunk.chunk_id] += rrf_score
                else:
                    scores[chunk.chunk_id] = rrf_score
                    chunk_map[chunk.chunk_id] = chunk

        # 按 RRF 分数排序
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        result = []
        for cid in sorted_ids:
            chunk = chunk_map[cid]
            chunk.score = scores[cid]
            chunk.raw_score = raw_scores.get(cid, 0.0)
            result.append(chunk)
        return result

    async def _rerank_health_ok(self) -> bool:
        """Reranker 服务可用性（TTL 缓存，避免每次请求 HTTP 健康检查往返）"""
        now = time.monotonic()
        if now - _rerank_health_cache["ts"] < RERANK_HEALTH_TTL_S:
            logger.debug("rag.rerank_health_cache_hit", ok=_rerank_health_cache["ok"])
            return _rerank_health_cache["ok"]
        logger.debug("rag.rerank_health_cache_miss")
        try:
            from app.providers.reranker import RerankProvider

            health = await RerankProvider().health_check()
            _rerank_health_cache["ok"] = bool(health.get("ok"))
        except Exception:
            _rerank_health_cache["ok"] = False
        _rerank_health_cache["ts"] = now
        return _rerank_health_cache["ok"]

    async def _rerank(
        self, query: str, chunks: list[ScoredChunk], *, request_id: str
    ) -> tuple[list[ScoredChunk], bool]:
        """Rerank 精排。

        返回 (chunks, used_reranker)。Reranker 不可用时降级为 RRF 排序直取。
        健康检查使用 TTL 缓存，避免每次请求都发起 HTTP 往返。
        """
        if chunks:
            try:
                from app.providers.reranker import RerankProvider

                if await self._rerank_health_ok():
                    reranker = RerankProvider()
                    pairs = await reranker.rerank(
                        query, [c.content for c in chunks], request_id=request_id
                    )
                    reranked: list[ScoredChunk] = []
                    for idx, score in pairs:
                        chunk = chunks[idx]
                        chunk.score = score
                        chunk.raw_score = max(chunk.raw_score, score)
                        reranked.append(chunk)
                    return reranked, True
            except Exception as e:
                logger.warning("rag.rerank_failed", error=str(e)[:200])

        # 降级：直接按 RRF 分数排序返回
        return sorted(chunks, key=lambda c: c.score, reverse=True), False

    def _to_scored_chunk(
        self, chunk: Chunk, default_score: float, raw_score: float = 0.0
    ) -> ScoredChunk:
        """将 ORM Chunk 转为 ScoredChunk"""
        return ScoredChunk(
            chunk_id=str(chunk.id),
            doc_id=str(chunk.doc_id),
            content=chunk.content or "",
            score=default_score,
            raw_score=raw_score,
            kp_ids=chunk.kp_ids if chunk.kp_ids else [],
        )


# ---- 全局单例 ----
_rag_pipeline: RAGPipeline | None = None


def get_rag_pipeline() -> RAGPipeline:
    """获取全局 RAGPipeline 单例"""
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = RAGPipeline()
    return _rag_pipeline
