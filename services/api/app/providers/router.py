"""Provider Router（providers/router.py）

星火主通道 + DeepSeek-v4-flash 兜底。
降级策略：星火超时/5xx/限流/连接错误 → 切 DeepSeek，返回结果如实标注 provider。
重试只许 1 次且仅对网络层错误；429/5xx 直接降级（§7.1 要求 2）。
流式降级纪律：主通道已输出 token 后失败 → 不重头重流（防重复输出），
发 _error 事件收尾；0 token 时才干净降级。
每次真实调用都落 ai_calls（audit，含 fallback 记录）。
"""

import time
from collections.abc import AsyncIterator

import structlog

from app.providers.audit import log_ai_call
from app.providers.base import ChatMessage, ChatResult
from app.providers.deepseek import DeepSeekProvider
from app.providers.spark import SparkProvider

logger = structlog.get_logger()


class ModelRouter:
    """星火主通道 + DeepSeek-v4-flash 兜底"""

    def __init__(self, spark: SparkProvider, deepseek: DeepSeekProvider) -> None:
        self._spark = spark
        self._deepseek = deepseek

    @staticmethod
    def _model_of(provider) -> str:
        return getattr(provider, "_model", provider.name)

    @property
    def intended_provider(self) -> str:
        """意向通道（供 SSE meta 标注；实际通道以流中 _provider 事件为准）"""
        return "spark" if self._spark.available else "deepseek"

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        functions: list[dict] | None = None,
        request_id: str,
        scene: str,
    ) -> ChatResult:
        """先星火；失败则降级 DeepSeek"""
        log = logger.bind(request_id=request_id, scene=scene)

        # 尝试星火主通道
        if self._spark.available:
            try:
                result = await self._spark.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    functions=functions,
                    request_id=request_id,
                    scene=scene,
                )
                log.info("router.chat.ok", provider="spark", latency_ms=result["latency_ms"])
                log_ai_call(
                    request_id=request_id,
                    scene=scene,
                    provider="spark",
                    model=self._model_of(self._spark),
                    input_tokens=result["input_tokens"],
                    output_tokens=result["output_tokens"],
                    latency_ms=result["latency_ms"],
                    status="success",
                )
                return result
            except Exception as e:
                log.warning("router.chat.fallback", primary="spark", error=str(e)[:200])
                log_ai_call(
                    request_id=request_id,
                    scene=scene,
                    provider="spark",
                    model=self._model_of(self._spark),
                    latency_ms=0,
                    status="error",
                    error=str(e)[:500],
                )

        # 降级 DeepSeek
        try:
            result = await self._deepseek.chat(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                functions=functions,
                request_id=request_id,
                scene=scene,
            )
            status = "fallback" if self._spark.available else "success"
            log.info("router.chat.ok", provider="deepseek", latency_ms=result["latency_ms"])
            log_ai_call(
                request_id=request_id,
                scene=scene,
                provider="deepseek",
                model=self._model_of(self._deepseek),
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                latency_ms=result["latency_ms"],
                status=status,
            )
            return result
        except Exception as e:
            log.exception("router.chat.all_failed")
            log_ai_call(
                request_id=request_id,
                scene=scene,
                provider="deepseek",
                model=self._model_of(self._deepseek),
                latency_ms=0,
                status="error",
                error=str(e)[:500],
            )
            raise RuntimeError("All model providers failed") from None

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        request_id: str,
        scene: str,
    ) -> AsyncIterator[dict]:
        """流式：先星火；失败则降级 DeepSeek。

        事件序列：{"_provider": str} → {"token": str}* → {"_usage": dict}?
        主通道已输出 token 后失败 → {"_error": {...}}（不重头重流）。
        """
        log = logger.bind(request_id=request_id, scene=scene)

        candidates: list[tuple[str, object]] = []
        if self._spark.available:
            candidates.append(("spark", self._spark))
        candidates.append(("deepseek", self._deepseek))

        tokens_yielded = 0
        idx = 0
        while idx < len(candidates):
            name, provider = candidates[idx]
            t0 = time.monotonic()
            out_chars = 0
            usage: dict = {}
            status = "success" if idx == 0 else "fallback"
            try:
                yield {"_provider": name}
                async for event in provider.chat_stream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_id=request_id,
                    scene=scene,
                ):
                    if "token" in event:
                        tokens_yielded += 1
                        out_chars += len(event["token"])
                        yield {"token": event["token"]}
                    elif "_usage" in event:
                        usage = event["_usage"] or {}
                        yield {"_usage": usage}
                latency = int((time.monotonic() - t0) * 1000)
                log.info("router.stream.ok", provider=name, latency_ms=latency)
                log_ai_call(
                    request_id=request_id,
                    scene=scene,
                    provider=name,
                    model=self._model_of(provider),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", max(1, out_chars // 2)),
                    latency_ms=latency,
                    status=status,
                )
                return
            except Exception as e:
                latency = int((time.monotonic() - t0) * 1000)
                log.warning("router.stream.fallback", primary=name, error=str(e)[:200])
                log_ai_call(
                    request_id=request_id,
                    scene=scene,
                    provider=name,
                    model=self._model_of(provider),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", max(1, out_chars // 2)),
                    latency_ms=latency,
                    status="error",
                    error=str(e)[:500],
                )
                if tokens_yielded > 0 or idx == len(candidates) - 1:
                    # 已向客户端输出部分内容，或无可降级 → 错误收尾，不重复输出
                    yield {
                        "_error": {
                            "code": 50301,
                            "message": "模型服务暂时不可用，请重试",
                            "recoverable": True,
                        }
                    }
                    return
                idx += 1  # 0 token 输出，干净降级下一通道


# ---- 全局单例 ----
_model_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    """获取全局 ModelRouter 单例"""
    global _model_router
    if _model_router is None:
        _model_router = ModelRouter(
            spark=SparkProvider(),
            deepseek=DeepSeekProvider(),
        )
    return _model_router


def get_spark() -> SparkProvider:
    return get_model_router()._spark


def get_deepseek() -> DeepSeekProvider:
    return get_model_router()._deepseek
