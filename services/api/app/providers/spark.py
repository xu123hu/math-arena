"""Spark Provider（providers/spark.py）

主通道 —— 星火大模型 HTTP 协议（禁止 WebSocket SDK，ADR-001-8）。
使用 OpenAI 兼容接口: https://spark-api-open.xf-yun.com/v1/chat/completions
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

SPARK_API_URL = "https://spark-api-open.xf-yun.com/v1/chat/completions"


class SparkProvider:
    """星火大模型主通道（HTTP 协议）"""

    name: str = "spark"

    def __init__(self) -> None:
        self._api_password = settings.spark_api_password
        self._model = settings.spark_model

    @property
    def available(self) -> bool:
        return bool(self._api_password)

    def _build_headers(self) -> dict[str, str]:
        # 星火 OpenAI 兼容接口使用 Bearer token 鉴权
        return {
            "Authorization": f"Bearer {self._api_password}",
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
            raise RuntimeError("Spark API password not configured")

        log = logger.bind(request_id=request_id, scene=scene, provider="spark")
        log.info("spark.chat.start", model=self._model, msg_count=len(messages))
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
                SPARK_API_URL,
                headers=self._build_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            message = data["choices"][0]["message"] or {}
            content = message.get("content") or ""
            # 防御性过滤：移除可能的 <think> 块
            content = strip_thinking(content)
            tool_calls = parse_tool_calls(message)
            usage = data.get("usage", {})
            latency = int((time.monotonic() - t0) * 1000)

            log.info(
                "spark.chat.ok",
                latency_ms=latency,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                has_tool_calls=bool(tool_calls),
            )

            return ChatResult(
                content=content,
                provider="spark",
                model=self._model,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                latency_ms=latency,
                tool_calls=tool_calls,
            )
        except httpx.HTTPStatusError as e:
            latency = int((time.monotonic() - t0) * 1000)
            log.error("spark.chat.http_error", status=e.response.status_code, latency_ms=latency)
            raise
        except Exception:
            latency = int((time.monotonic() - t0) * 1000)
            log.exception("spark.chat.error", latency_ms=latency)
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
            raise RuntimeError("Spark API password not configured")

        log = logger.bind(request_id=request_id, scene=scene, provider="spark")
        log.info("spark.stream.start", model=self._model, msg_count=len(messages))

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
            SPARK_API_URL,
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
                        # 防御性过滤 <think> 块 + 压缩多余空行
                        filtered = think_filter.process(text)
                        if filtered:
                            filtered = nl_compressor.process(filtered)
                        if filtered:
                            yield {"token": filtered}
                    if finish_reason:
                        log.info("spark.stream.finish", finish_reason=finish_reason)
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

        # 流结束：刷出过滤器 / 压缩器 buffer 中的残留内容
        remaining = think_filter.flush()
        if remaining:
            remaining = nl_compressor.process(remaining)
        if remaining:
            yield {"token": remaining}

        log.info("spark.stream.done")

    async def health_check(self) -> dict:
        """探测星火通道可用性"""
        if not self.available:
            return {"ok": False, "latency_ms": 0, "error": "API key not configured"}

        t0 = time.monotonic()
        client = get_http()
        try:
            resp = await client.post(
                SPARK_API_URL,
                headers=self._build_headers(),
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
            )
            resp.raise_for_status()
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": True, "latency_ms": latency}
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "error": str(e)[:200]}
