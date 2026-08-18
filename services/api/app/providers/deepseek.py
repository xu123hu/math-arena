"""DeepSeek Provider（providers/deepseek.py）

备用通道，OpenAI 兼容协议。
model: deepseek-v4-flash（deepseek-chat 于 2026-07-24 弃用，ADR-001-8）
"""

import json
import re
import time
from collections.abc import AsyncIterator

import httpx
import structlog

from app.config import settings
from app.providers.base import (
    ChatMessage,
    ChatResult,
    NewlineCompressor,
    ThinkingFilter,
    parse_tool_calls,
    strip_thinking,
)
from app.providers.http import get_http

logger = structlog.get_logger()


class DeepSeekProvider:
    """DeepSeek-v4-flash 备用通道"""

    name: str = "deepseek"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        thinking: bool | None = None,
    ) -> None:
        self._api_key = api_key or settings.deepseek_api_key
        self._model = model or settings.deepseek_model
        self._thinking = thinking if thinking is not None else settings.deepseek_thinking
        self._api_url = base_url or settings.deepseek_base_url

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        stream: bool = False,
        functions: list[dict] | None = None,
        thinking: bool | None = None,
    ) -> dict:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        # ADR-001-8: 聊天场景默认关闭深度思考（thinking 为顶层字段，
        # extra_body 是 OpenAI SDK 客户端概念，直接放进 HTTP body 无效）
        # per-call thinking 覆盖 > 实例/全局配置
        thinking_on = thinking if thinking is not None else self._thinking
        if not thinking_on:
            payload["thinking"] = {"type": "disabled"}
        if stream:
            # 让流末返回真实 usage（OpenAI 兼容）
            payload["stream_options"] = {"include_usage": True}
        if functions:
            payload["tools"] = [{"type": "function", "function": f} for f in functions]
        return payload

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
        if not self.available:
            raise RuntimeError("DeepSeek API key not configured")

        log = logger.bind(request_id=request_id, scene=scene, provider="deepseek")
        log.info("deepseek.chat.start", model=self._model, msg_count=len(messages))
        t0 = time.monotonic()

        client = get_http()
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            functions=functions,
            thinking=thinking,
        )

        try:
            resp = await client.post(
                self._api_url,
                headers=self._build_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            message = data["choices"][0]["message"] or {}
            content = message.get("content") or ""
            # 过滤 thinking 内容（防御 mimo 等模型返回 <think> 块）
            content = strip_thinking(content)
            tool_calls = parse_tool_calls(message)
            usage = data.get("usage", {})
            latency = int((time.monotonic() - t0) * 1000)

            log.info(
                "deepseek.chat.ok",
                latency_ms=latency,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                has_tool_calls=bool(tool_calls),
            )

            return ChatResult(
                content=content,
                provider="deepseek",
                model=self._model,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency,
                tool_calls=tool_calls,
            )
        except httpx.HTTPStatusError as e:
            latency = int((time.monotonic() - t0) * 1000)
            log.error("deepseek.chat.http_error", status=e.response.status_code, latency_ms=latency)
            raise
        except Exception:
            latency = int((time.monotonic() - t0) * 1000)
            log.exception("deepseek.chat.error", latency_ms=latency)
            raise

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
        """流式生成。yield {"token": str} 或 {"_usage": dict}（流末真实用量）。

        emit_thinking=True 时，额外 yield {"thinking": str} 承载思考片段（M2 重构）。
        """
        if not self.available:
            raise RuntimeError("DeepSeek API key not configured")

        log = logger.bind(request_id=request_id, scene=scene, provider="deepseek")
        log.info("deepseek.stream.start", model=self._model, msg_count=len(messages))

        think_filter = ThinkingFilter(emit_thinking=emit_thinking)
        nl_compressor = NewlineCompressor()
        last_finish: str | None = None  # v1.3：记录流末 finish_reason，末尾以 _finish 事件透出（供截断续写判定）

        # 迭代18：末尾免责声明缓冲。小米 MiMo 会在回复末尾追加
        # "|部分内容可能由AI生成"（平台侧注入，跨多 token）。逐 token 已无法收回，
        # 故缓冲末尾 _TAIL_HOLD_CHARS 字符，流结束时清洗尾巴后发出；首 token 零延迟。
        _TAIL_HOLD_CHARS = 48
        _AI_GEN_TAIL_RE = re.compile(r"[\s｜|]*部分内容可能由AI生成[。.!！]*\s*$")
        tail_buf = ""

        client = get_http()
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            thinking=thinking,
        )

        async with client.stream(
            "POST",
            self._api_url,
            headers=self._build_headers(),
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    # 流末 usage chunk（choices 为空）
                    if chunk.get("usage") and not chunk.get("choices"):
                        yield {"_usage": chunk["usage"]}
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason")
                    # M2 重构：思考内容两种承载方式都兼容——
                    # ① delta.reasoning_content 独立字段（DeepSeek/星火官方协议）
                    # ② delta.content 内嵌 <think> 标签（mimo 等模型，走 ThinkingFilter）
                    reasoning = delta.get("reasoning_content", "")
                    if reasoning and emit_thinking:
                        yield {"thinking": reasoning}
                    text = delta.get("content", "")
                    if text:
                        # 过滤 <think> 块 + 压缩多余空行
                        filtered = think_filter.process(text)
                        # M2 重构：思考片段旁路下发
                        if emit_thinking and think_filter.last_thinking:
                            yield {"thinking": think_filter.last_thinking}
                        if filtered:
                            filtered = nl_compressor.process(filtered)
                        if filtered:
                            # 迭代18：进尾部缓冲，超出的部分实时下发
                            tail_buf += filtered
                            if len(tail_buf) > _TAIL_HOLD_CHARS:
                                yield {"token": tail_buf[:-_TAIL_HOLD_CHARS]}
                                tail_buf = tail_buf[-_TAIL_HOLD_CHARS:]
                    if finish_reason:
                        log.info("deepseek.stream.finish", finish_reason=finish_reason)
                        last_finish = finish_reason
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        # 流结束：刷出过滤器 / 压缩器 buffer 中的残留内容
        remaining = think_filter.flush()
        if remaining:
            remaining = nl_compressor.process(remaining)
        if remaining:
            tail_buf += remaining
        # 迭代18：清洗免责尾巴后发出尾部缓冲（去掉"|部分内容可能由AI生成"）
        if tail_buf:
            cleaned = _AI_GEN_TAIL_RE.sub("", tail_buf).rstrip()
            if cleaned:
                yield {"token": cleaned}

        # v1.3：透出 finish_reason（length=截断），技能层据此断点续写而非整段重想
        yield {"_finish": last_finish or "stop"}
        log.info("deepseek.stream.done")

    async def health_check(self) -> dict:
        """探测 DeepSeek 通道可用性"""
        if not self.available:
            return {"ok": False, "latency_ms": 0, "error": "API key not configured"}

        t0 = time.monotonic()
        client = get_http()
        try:
            resp = await client.post(
                self._api_url,
                headers=self._build_headers(),
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "thinking": {"type": "disabled"},
                },
            )
            resp.raise_for_status()
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": True, "latency_ms": latency, "model": self._model}
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "error": str(e)[:200]}
