"""Provider Router（providers/router.py）

星火主通道 + DeepSeek-v4-flash 兜底。
降级策略：星火超时(>20s)/5xx/限流 → 切 DeepSeek，返回结果如实标注 provider。
重试只许 1 次且仅对网络层错误；429/5xx 直接降级（§7.1 要求 2）。
"""

from collections.abc import AsyncIterator

import httpx
import structlog

from app.providers.base import ChatMessage, ChatResult
from app.providers.deepseek import DeepSeekProvider
from app.providers.spark import SparkProvider

logger = structlog.get_logger()


class ModelRouter:
    """星火主通道 + DeepSeek-v4-flash 兜底"""

    def __init__(self, spark: SparkProvider, deepseek: DeepSeekProvider) -> None:
        self._spark = spark
        self._deepseek = deepseek

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
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
                return result
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as e:
                log.warning("router.chat.fallback", primary="spark", error=str(e)[:200])
                # 降级到 DeepSeek
            except Exception as e:
                log.warning("router.chat.fallback", primary="spark", error=str(e)[:200])

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
            log.info("router.chat.ok", provider="deepseek", latency_ms=result["latency_ms"])
            return result
        except Exception:
            log.exception("router.chat.all_failed")
            raise RuntimeError("All model providers failed") from None

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        request_id: str,
        scene: str,
    ) -> AsyncIterator[str]:
        """流式：先星火；失败则降级 DeepSeek"""
        log = logger.bind(request_id=request_id, scene=scene)

        if self._spark.available:
            try:
                async for token in self._spark.chat_stream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    request_id=request_id,
                    scene=scene,
                ):
                    yield token
                return
            except Exception as e:
                log.warning("router.stream.fallback", primary="spark", error=str(e)[:200])

        # 降级 DeepSeek
        async for token in self._deepseek.chat_stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            request_id=request_id,
            scene=scene,
        ):
            yield token


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
