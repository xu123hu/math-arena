"""DeepSeek Provider（providers/deepseek.py）

备用通道，OpenAI 兼容协议。
model: deepseek-v4-flash（deepseek-chat 于 2026-07-24 弃用，ADR-001-8）
"""

import json
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

    def __init__(self) -> None:
        self._api_key = settings.deepseek_api_key
        self._model = settings.deepseek_model
        self._thinking = settings.deepseek_thinking
        self._api_url = settings.deepseek_base_url

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
        if not self._thinking:
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
        request_id: str,
        scene: str,
    ) -> AsyncIterator[dict]:
        """流式生成。yield {"token": str} 或 {"_usage": dict}（流末真实用量）。"""
        if not self.available:
            raise RuntimeError("DeepSeek API key not configured")

        log = logger.bind(request_id=request_id, scene=scene, provider="deepseek")
        log.info("deepseek.stream.start", model=self._model, msg_count=len(messages))

        think_filter = ThinkingFilter()
        nl_compressor = NewlineCompressor()

        client = get_http()
        payload = self._build_payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
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
                    text = delta.get("content", "")
                    if text:
                        # 过滤 <think> 块 + 压缩多余空行
                        filtered = think_filter.process(text)
                        if filtered:
                            filtered = nl_compressor.process(filtered)
                        if filtered:
                            yield {"token": filtered}
                    if finish_reason:
                        log.info("deepseek.stream.finish", finish_reason=finish_reason)
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        # 流结束：刷出过滤器 / 压缩器 buffer 中的残留内容
        remaining = think_filter.flush()
        if remaining:
            remaining = nl_compressor.process(remaining)
        if remaining:
            yield {"token": remaining}

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
