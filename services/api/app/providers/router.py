"""Provider Router（providers/router.py）

星火主通道 + DeepSeek-v4-flash 兜底。
降级策略：星火超时/5xx/限流/连接错误 → 切 DeepSeek，返回结果如实标注 provider。
重试只许 1 次且仅对网络层错误；429/5xx 直接降级（§7.1 要求 2）。
流式降级纪律：主通道已输出 token 后失败 → 不重头重流（防重复输出），
发 _error 事件收尾；0 token 时才干净降级。
每次真实调用都落 ai_calls（audit，含 fallback 记录）。

三层回退（管理后台 model.global）：
用户配置 > system_configs["model.global"] > env；
无用户配置时走带缓存的全局有效 router（TTL 60s，管理后台 PUT 后立即清缓存）。
"""

import json
import time
from collections.abc import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.audit import log_ai_call
from app.providers.base import ChatMessage, ChatResult
from app.providers.crypto import decrypt_api_key
from app.providers.deepseek import DeepSeekProvider
from app.providers.spark import SparkProvider

logger = structlog.get_logger()

# ---- 主通道熔断（M2 规格 §2.11.1）----
# 主通道连续失败 ≥2 次/10min 则熔断 5min 直接走备用，避免每请求白等主通道超时；
# 成功后自动恢复。状态按主通道配置指纹模块级共享——per-user router 每请求重建，
# 熔断状态挂实例上会被冲掉，故以 (api_url, model) 为键共享。
_CIRCUIT: dict[str, dict] = {}
_CIRCUIT_FAIL_WINDOW_S = 600  # 连续失败统计窗口 10min
_CIRCUIT_FAIL_THRESHOLD = 2  # 窗口内 ≥2 次失败即熔断
_CIRCUIT_OPEN_S = 300  # 熔断时长 5min


class ModelRouter:
    """星火主通道 + DeepSeek-v4-flash 兜底"""

    def __init__(self, spark: SparkProvider, deepseek: DeepSeekProvider) -> None:
        self._spark = spark
        self._deepseek = deepseek

    @staticmethod
    def _model_of(provider) -> str:
        return getattr(provider, "_model", provider.name)

    # ---- 熔断状态 ----

    def _circuit_state(self) -> dict:
        key = f"{getattr(self._spark, '_api_url', '')}|{self._model_of(self._spark)}"
        return _CIRCUIT.setdefault(key, {"failures": [], "open_until": 0.0})

    def _primary_usable(self) -> bool:
        """主通道当前可用（有配置且未熔断）"""
        return self._spark.available and time.monotonic() >= self._circuit_state()["open_until"]

    def _record_primary_success(self) -> None:
        st = self._circuit_state()
        was_open = time.monotonic() < st["open_until"]
        if st["failures"] or st["open_until"]:
            st["failures"] = []
            st["open_until"] = 0.0
            if was_open:
                logger.info("router.circuit.closed", model=self._model_of(self._spark))

    def _record_primary_failure(self) -> None:
        st = self._circuit_state()
        now = time.monotonic()
        st["failures"] = [t for t in st["failures"] if now - t < _CIRCUIT_FAIL_WINDOW_S]
        st["failures"].append(now)
        if len(st["failures"]) >= _CIRCUIT_FAIL_THRESHOLD and now >= st["open_until"]:
            st["open_until"] = now + _CIRCUIT_OPEN_S
            logger.warning(
                "router.circuit.open",
                model=self._model_of(self._spark),
                failures=len(st["failures"]),
                open_seconds=_CIRCUIT_OPEN_S,
            )

    @property
    def intended_provider(self) -> str:
        """意向通道（供 SSE meta 标注；实际通道以流中 _provider 事件为准）"""
        return "spark" if self._primary_usable() else "deepseek"

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        functions: list[dict] | None = None,
        thinking: bool | None = None,
        request_id: str,
        scene: str,
    ) -> ChatResult:
        """先星火；失败则降级 DeepSeek。thinking=None 时按 provider 默认/全局配置"""
        log = logger.bind(request_id=request_id, scene=scene)

        # 尝试星火主通道（熔断期内直接跳过走备用）
        if self._primary_usable():
            try:
                result = await self._spark.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    functions=functions,
                    thinking=thinking,
                    request_id=request_id,
                    scene=scene,
                )
                self._record_primary_success()
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
                self._record_primary_failure()
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
                thinking=thinking,
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
        thinking: bool | None = None,
        request_id: str,
        scene: str,
        emit_thinking: bool = False,
    ) -> AsyncIterator[dict]:
        """流式：先星火；失败则降级 DeepSeek。

        事件序列：{"_provider": str} → {"token": str}* → {"_usage": dict}?
        主通道已输出 token 后失败 → {"_error": {...}}（不重头重流）。
        thinking=None 时按 provider 默认/全局配置。
        emit_thinking=True 时额外透传 {"thinking": str} 思考片段事件（M2 重构）。
        """
        log = logger.bind(request_id=request_id, scene=scene)

        candidates: list[tuple[str, object]] = []
        if self._primary_usable():
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
                    thinking=thinking,
                    request_id=request_id,
                    scene=scene,
                    **({"emit_thinking": True} if emit_thinking else {}),
                ):
                    if "token" in event:
                        tokens_yielded += 1
                        out_chars += len(event["token"])
                        yield {"token": event["token"]}
                    elif "thinking" in event:
                        yield {"thinking": event["thinking"]}
                    elif "_finish" in event:
                        # v1.3：透传 finish_reason（length=截断），技能层据此断点续写
                        yield {"_finish": event["_finish"]}
                    elif "_usage" in event:
                        usage = event["_usage"] or {}
                        yield {"_usage": usage}
                latency = int((time.monotonic() - t0) * 1000)
                if name == "spark":
                    self._record_primary_success()
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
                if name == "spark":
                    self._record_primary_failure()
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


# ---- model.global 三层回退（用户配置 > system_configs["model.global"] > env） ----

# model.global 读取缓存：TTL 60s；管理后台 PUT 后调 clear_global_model_config_cache 立即失效
_global_model_cfg_cache: tuple[float, dict] | None = None
_GLOBAL_MODEL_CFG_TTL_S = 60.0

# 全局有效 router 缓存：overrides 指纹 → router（指纹变化即重建，避免旧密钥泄漏）
_global_effective_router: tuple[str, ModelRouter] | None = None


def clear_global_model_config_cache() -> None:
    """model.global 更新后调用：同时失效配置缓存与全局有效 router"""
    global _global_model_cfg_cache, _global_effective_router
    _global_model_cfg_cache = None
    _global_effective_router = None


async def _load_global_model_overrides(db: AsyncSession) -> dict:
    """读取 system_configs["model.global"]（带 TTL 缓存；api_key 仍为密文）"""
    global _global_model_cfg_cache
    now = time.monotonic()
    if (
        _global_model_cfg_cache is not None
        and now - _global_model_cfg_cache[0] < _GLOBAL_MODEL_CFG_TTL_S
    ):
        return _global_model_cfg_cache[1]

    from app.models.system_config import get_system_config

    value = await get_system_config(db, "model.global", default={})
    if not isinstance(value, dict):  # 防御脏数据：非 dict 视为无全局配置
        value = {}
    _global_model_cfg_cache = (now, value)
    return value


def _channel_overrides(overrides: dict, channel: str) -> dict:
    """取单通道覆盖 dict，非 dict 一律视为空覆盖"""
    value = overrides.get(channel)
    return value if isinstance(value, dict) else {}


def _decrypted(value) -> str | None:
    """密文解密为可用 key；空值/非字符串/损坏密文 → None（回退下一层）"""
    if not value or not isinstance(value, str):
        return None
    return decrypt_api_key(value) or None


def _bool_or_none(value) -> bool | None:
    return value if isinstance(value, bool) else None


def _build_router_from_overrides(overrides: dict) -> ModelRouter:
    """按 {"primary": {...}, "secondary": {...}} 覆盖构造 router（缺字段回退 env）"""
    primary = _channel_overrides(overrides, "primary")
    secondary = _channel_overrides(overrides, "secondary")
    spark = SparkProvider(
        api_password=_decrypted(primary.get("api_key")),
        model=primary.get("model") or None,
        base_url=primary.get("base_url") or None,
        thinking=_bool_or_none(primary.get("thinking")),
    )
    deepseek = DeepSeekProvider(
        api_key=_decrypted(secondary.get("api_key")),
        model=secondary.get("model") or None,
        base_url=secondary.get("base_url") or None,
        thinking=_bool_or_none(secondary.get("thinking")),
    )
    return ModelRouter(spark=spark, deepseek=deepseek)


async def get_model_router_global(db: AsyncSession) -> ModelRouter:
    """全局有效 ModelRouter（env ← model.global）

    无 model.global 覆盖 → env 单例 get_model_router()（零开销）；
    有覆盖 → 按内容指纹缓存重建（TTL 与 PUT 清缓存双保险）。
    """
    global _global_effective_router
    overrides = await _load_global_model_overrides(db)
    if not overrides:
        return get_model_router()

    fingerprint = json.dumps(overrides, sort_keys=True, default=str)
    if _global_effective_router is not None and _global_effective_router[0] == fingerprint:
        return _global_effective_router[1]
    router = _build_router_from_overrides(overrides)
    _global_effective_router = (fingerprint, router)
    return router


async def get_model_router_for_user(
    user_id: str,
    db: AsyncSession,
) -> ModelRouter:
    """获取 per-user ModelRouter（三层回退：用户配置 > model.global > env）

    - 无用户配置 → 全局有效 router get_model_router_global(db)
    - 有用户配置 → 字段级回退：用户字段 > model.global > env
    """
    from app.models.user_model_config import UserModelConfig

    result = await db.execute(select(UserModelConfig).where(UserModelConfig.user_id == user_id))
    cfg = result.scalar_one_or_none()
    if cfg is None:
        return await get_model_router_global(db)

    overrides = await _load_global_model_overrides(db)
    primary_g = _channel_overrides(overrides, "primary")
    secondary_g = _channel_overrides(overrides, "secondary")

    # 字段级回退构造 Provider：用户密文 > model.global 密文 > env（构造器内回退 settings）
    spark = SparkProvider(
        api_password=(
            decrypt_api_key(cfg.primary_api_key)
            if cfg.primary_api_key
            else _decrypted(primary_g.get("api_key"))
        ),
        model=cfg.primary_model or primary_g.get("model") or None,
        base_url=cfg.primary_base_url or primary_g.get("base_url") or None,
        # 用户配置无 primary thinking 字段，取自 model.global 或 env
        thinking=_bool_or_none(primary_g.get("thinking")),
    )
    deepseek = DeepSeekProvider(
        api_key=(
            decrypt_api_key(cfg.secondary_api_key)
            if cfg.secondary_api_key
            else _decrypted(secondary_g.get("api_key"))
        ),
        model=cfg.secondary_model or secondary_g.get("model") or None,
        base_url=cfg.secondary_base_url or secondary_g.get("base_url") or None,
        thinking=(
            cfg.secondary_thinking
            if cfg.secondary_thinking is not None
            else _bool_or_none(secondary_g.get("thinking"))
        ),
    )
    return ModelRouter(spark=spark, deepseek=deepseek)
