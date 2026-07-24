"""教材答疑技能（skills/qa_rag/main.py）

验证 RAG 管线的最小闭环，是 M2 所有知识型 skill 的模板（§8.4）。
流程：rag.retrieve → answerable? → 流式回答 + citation
事件纪律同 chat：透传 _usage/_provider/_error，中途失败保留部分回答。
"""

import time
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import text

from app.skills.base import SkillContext, SkillExecutor

logger = structlog.get_logger()

# 拒答降级话术
REFUSE_MESSAGE = (
    "这个问题超出了我目前教材知识库的范围。"
    "我可以基于通用数学能力尝试回答，但答案未关联教材内容，仅供参考。\n\n"
    "如果你需要更精确的教材解答，可以：\n"
    "1. 换个方式描述问题\n"
    "2. 指定具体的知识点或章节\n"
    "3. 等待联网搜索功能上线"
)

QA_SYSTEM_SUFFIX = r"""

## 回答要求（教材答疑模式）
1. 严格基于给定的参考资料回答
2. 引用处必须标注【N】（N 为资料编号）
3. 如果资料不足以完整回答，明确说明哪部分是资料内容，哪部分是补充
4. 不要编造不存在的引用
5. 数学公式使用 LaTeX 格式：行内用 \(...\)，独立公式用 $$...$$
6. 分步推理，每步给出依据，重要结论加粗"""


class QaRagSkill(SkillExecutor):
    """教材答疑技能"""

    manifest = {
        "id": "qa_rag",
        "name": "教材答疑",
        "version": "1.0.0",
        "description": (
            "解答高中数学知识点疑问，基于教材知识库给出带引用的回答。"
            "适用于概念解释、定理说明、公式推导、教材内容查询、"
            "知识库内容概览、知识点目录浏览等。"
        ),
        "trigger": ["概念是什么", "这步为什么", "什么是", "怎么理解", "知识库里有什么", "有哪些知识点"],
        "entry": "main:QaRagSkill",
        "permissions": ["knowledge.read"],
        "roles": ["student", "teacher", "researcher"],
        "presentation": "inline",
        "params_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "用户问题原文"},
            },
            "required": ["question"],
        },
        "context_contract": {
            "need_rag": True,
            "need_profile": False,
            "max_history_turns": 10,
        },
    }

    # 元问题关键词
    META_KEYWORDS = [
        "知识库里有什么", "有哪些知识", "知识库内容", "你能查什么",
        "知识库目录", "有哪些知识点", "知识库里有哪些", "你能回答什么",
    ]

    async def run(self, params: dict, ctx: SkillContext) -> AsyncIterator[dict]:
        """执行教材答疑

        流程：
        0. 元问题检测 → 直接返回文档目录
        1. rag.retrieve() 检索知识库
        2. answerable=False → notice 降级话术
        3. answerable=True → chunks 进上下文 → 流式回答 → citations
        """
        question = params.get("question", "")
        t0 = time.monotonic()

        try:
            # 0. 元问题检测：直接查询文档列表，不走完整RAG
            is_meta = any(kw in question for kw in self.META_KEYWORDS)
            if is_meta:
                logger.info("qa_rag.meta_query", request_id=ctx.request_id, question=question)
                result = await ctx.db.execute(
                    text("SELECT title, source_type FROM knowledge_docs WHERE status = 'active' AND deleted_at IS NULL ORDER BY created_at DESC")
                )
                docs = result.fetchall()
                if docs:
                    doc_list = "\n".join([f"- {d[0]}（{d[1]}）" for d in docs])
                    response_text = f"当前知识库包含以下文档：\n{doc_list}\n\n你可以就这些文档中的内容向我提问。"
                else:
                    response_text = "当前知识库暂无可用文档。"

                # 通过流式 token 事件返回
                yield {"type": "token", "data": {"text": response_text}}
                yield {
                    "type": "_result_meta",
                    "data": {
                        "full_text": response_text,
                        "provider": "meta",
                        "latency_ms": int((time.monotonic() - t0) * 1000),
                        "usage": {},
                        "degraded": False,
                        "meta_query": True,
                    },
                }
                return

            # 1. RAG 检索
            yield {
                "type": "status",
                "data": {"stage": "retrieving", "text": "正在检索教材知识库..."},
            }

            # 获取工作记忆（供 RAG 改写复用 recent_messages，降级路径上下文装配也复用）
            working_memory = None
            if ctx.memory:
                working_memory = await ctx.memory.get_working_memory(ctx.conversation_id, ctx.db)

            rag_result = None
            if ctx.rag:
                # 复用工作记忆中的最近消息作为 RAG 改写历史
                history = working_memory.recent_messages if working_memory else []

                rag_result = await ctx.rag.retrieve(
                    question,
                    db=ctx.db,
                    conversation_history=history,
                    conversation_id=ctx.conversation_id,
                    request_id=ctx.request_id,
                )

            # 获取用户档案（降级路径上下文装配需要；正常路径不使用）
            user_profile = None
            if ctx.memory:
                user_profile = await ctx.memory.get_user_profile(ctx.user_id, ctx.db)

            # 2. 判断是否可答
            if rag_result is None or not rag_result.answerable:
                # 拒答降级：通用能力回答（标注未关联教材）
                yield {
                    "type": "status",
                    "data": {"stage": "thinking", "text": "知识库未找到相关内容"},
                }

                # 降级路径改用 ContextAssembler 装配完整上下文（含对话历史与用户档案）
                # 替代原先只含 question 的裸 messages，避免答非所问问题
                if ctx.context_assembler:
                    messages = await ctx.context_assembler.assemble(
                        user_message=question,
                        active_role=ctx.user_role,
                        working_memory=working_memory,
                        user_profile=user_profile,
                        output_spec=(
                            "以下回答未基于教材知识库。如果概念确实存在但超出教材范围，"
                            "基于通用数学能力简要回答并标注'以下非教材内容，仅供参考'。"
                            "如果概念不存在或你无法确认，明确告知。"
                            "禁止使用【1】【2】等引用标记，不要编造任何教材引用。"
                        ),
                    )
                else:
                    # 降级：ContextAssembler 不可用时手动构建（分级响应 prompt）
                    messages = [
                        {
                            "role": "system",
                            "content": (
                                "你是一位数学助手。知识库中没有找到相关内容。\n\n"
                                "分级响应规则：\n"
                                "1. 如果用户提到的数学概念、定理或公式在你的知识中确实不存在"
                                "或你无法确认其真实性，直接告知'我无法确认该概念的真实性'\n"
                                "2. 如果概念确实存在但超出教材范围（如薛定谔方程、黎曼猜想等），"
                                "基于你的通用数学能力给出准确、简洁的解释，"
                                "并在开头标注'以下内容超出当前教材范围，仅供参考'\n"
                                "3. 如果用户追问表达强烈求知意愿（如'我很想知道'、'你能告诉我吗'），"
                                "应尊重并给出你能确定的解答\n\n"
                                "数学公式使用 LaTeX 格式：行内用 \\(...\\)，独立公式用 $$...$$。\n"
                                "重要：以下回答未基于教材知识库，禁止使用【1】【2】等引用标记，不要编造任何教材引用。"
                            ),
                        },
                        {"role": "user", "content": question},
                    ]

                async for out in self._stream_generate(
                    ctx,
                    messages,
                    scene="qa_rag_fallback",
                    degraded=True,
                    notice="未关联教材，按通用能力回答",
                    t0=t0,
                ):
                    yield out
                return

            # 3. 有知识库内容，构建带引用的回答
            yield {
                "type": "status",
                "data": {"stage": "generating", "text": "正在基于教材生成回答..."},
            }

            # 构建 RAG chunks 数据
            rag_chunks = [
                {"content": c.content, "doc_title": c.doc_title, "chunk_id": c.chunk_id}
                for c in rag_result.chunks
            ]

            # 上下文装配（带 RAG chunks）
            if ctx.context_assembler:
                messages = await ctx.context_assembler.assemble(
                    user_message=question,
                    active_role=ctx.user_role,
                    rag_chunks=rag_chunks,
                    output_spec="严格基于参考资料回答，引用处标注【N】。",
                )
            else:
                # 降级：手动构建
                chunks_text = "\n\n".join(
                    f"【{i+1}】{c['content']}" for i, c in enumerate(rag_chunks)
                )
                messages = [
                    {
                        "role": "system",
                        "content": f"基于以下资料回答，引用标注【N】：\n{chunks_text}",
                    },
                    {"role": "user", "content": question},
                ]

            # 4. 流式生成
            async for out in self._stream_generate(
                ctx,
                messages,
                scene="qa_rag",
                t0=t0,
                extra_meta={"chunks_used": len(rag_chunks)},
            ):
                yield out

            # 5. 设置 citations（交给主链路发 citation 事件）
            citations = [
                {
                    "n": i + 1,
                    "chunk_id": c.chunk_id,
                    "source": c.doc_title or "教材",
                    "loc": f"切片 {c.chunk_id[:8]}",
                }
                for i, c in enumerate(rag_result.chunks)
            ]
            ctx.set_citations(citations)

            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "qa_rag.skill.done",
                request_id=ctx.request_id,
                latency_ms=latency_ms,
                chunks_used=len(rag_chunks),
            )

        except Exception:
            logger.exception("qa_rag.skill.error", request_id=ctx.request_id)
            yield {
                "type": "error",
                "data": {"code": 50001, "message": "服务繁忙，请稍后重试", "recoverable": True},
            }

    async def _stream_generate(
        self,
        ctx: SkillContext,
        messages: list[dict],
        *,
        scene: str,
        t0: float,
        degraded: bool = False,
        notice: str = "",
        extra_meta: dict | None = None,
    ) -> AsyncIterator[dict]:
        """统一的流式生成 + 事件处理（token/status fallback/_usage/_error）"""
        if ctx.llm is None:
            yield {
                "type": "error",
                "data": {"code": 50001, "message": "模型不可用", "recoverable": False},
            }
            return

        full_text = ""
        provider_name = "deepseek"
        usage: dict = {}
        provider_error: dict | None = None
        first_provider: str | None = None

        async for event in ctx.llm.chat_stream(
            messages,
            temperature=0.3,
            max_tokens=8192,
            request_id=ctx.request_id,
            scene=scene,
        ):
            if "_provider" in event:
                new_provider = event["_provider"]
                if first_provider is not None and new_provider != first_provider:
                    yield {
                        "type": "status",
                        "data": {"stage": "fallback", "text": "主通道不可用，已切换备用模型"},
                    }
                first_provider = first_provider or new_provider
                provider_name = new_provider
                continue
            if "_usage" in event:
                usage = event["_usage"] or {}
                continue
            if "_error" in event:
                provider_error = event["_error"]
                break
            if "token" in event:
                full_text += event["token"]
                yield {"type": "token", "data": {"text": event["token"]}}

        if provider_error and not full_text:
            yield {
                "type": "error",
                "data": {
                    "code": provider_error.get("code", 50301),
                    "message": "模型服务暂时不可用，请稍后重试",
                    "recoverable": True,
                },
            }
            return

        latency_ms = int((time.monotonic() - t0) * 1000)
        meta = {
            "full_text": full_text,
            "provider": provider_name,
            "latency_ms": latency_ms,
            "usage": usage,
            "degraded": degraded,
        }
        if notice:
            meta["notice"] = notice
        if provider_error:
            # 已输出部分内容后通道中断：保留部分回答，如实标记
            meta["interrupted"] = True
            meta["notice"] = (notice + "；" if notice else "") + "模型服务中断，以上回答可能不完整"
        if extra_meta:
            meta.update(extra_meta)

        yield {"type": "_result_meta", "data": meta}
