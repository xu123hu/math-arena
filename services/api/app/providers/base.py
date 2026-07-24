"""模型服务层协议（providers/base.py）

所有模型调用都走这里，禁止在别处直连模型。
"""

import re
from collections.abc import AsyncIterator
from typing import Protocol, TypedDict


class ThinkingFilter:
    """流式过滤 <think>...</think> 思考链内容，处理标签跨 token 分片。

    状态机方式逐 token 过滤：
    - _in_think=True 时丢弃内容，直到发现 </think>
    - _in_think=False 时正常输出，遇到 <think> 进入过滤模式
    - 末尾保留 ≤6 / ≤8 字符防止标签跨 token 被截断
    """

    _OPEN = "<think>"   # 7 chars
    _CLOSE = "</think>"  # 8 chars

    def __init__(self) -> None:
        self._in_think: bool = False
        self._buffer: str = ""

    def process(self, token: str) -> str:
        """处理一个 token，返回过滤后的文本（可能为空字符串）"""
        self._buffer += token
        result = ""

        while self._buffer:
            if self._in_think:
                idx = self._buffer.find(self._CLOSE)
                if idx != -1:
                    self._in_think = False
                    self._buffer = self._buffer[idx + len(self._CLOSE):]
                else:
                    # 保留最后 8 字符（"</think>" 长度），防止 </think> 跨 token
                    if len(self._buffer) > len(self._CLOSE):
                        self._buffer = self._buffer[-len(self._CLOSE):]
                    break
            else:
                idx = self._buffer.find(self._OPEN)
                if idx != -1:
                    result += self._buffer[:idx]
                    self._in_think = True
                    self._buffer = self._buffer[idx + len(self._OPEN):]
                else:
                    # 保留最后 6 字符（len("<think>")-1），防止 <think> 跨 token
                    hold = len(self._OPEN) - 1  # 6
                    safe_len = max(0, len(self._buffer) - hold)
                    result += self._buffer[:safe_len]
                    self._buffer = self._buffer[safe_len:]
                    break

        return result

    def flush(self) -> str:
        """流结束时刷出 buffer 中残留内容（不可能是完整标签的前缀）"""
        remaining = self._buffer
        self._buffer = ""
        return remaining


class NewlineCompressor:
    """流式压缩连续换行：将 3+ 个连续 \n 压缩为 2 个（即一个空行）"""

    def __init__(self) -> None:
        self._nl_count: int = 0

    def process(self, text: str) -> str:
        if not text:
            return text
        result: list[str] = []
        for ch in text:
            if ch == "\n":
                self._nl_count += 1
                if self._nl_count <= 2:
                    result.append(ch)
            else:
                self._nl_count = 0
                result.append(ch)
        return "".join(result)

    def flush(self) -> str:
        """流结束时可丢弃末尾多余换行（不需要额外输出）"""
        self._nl_count = 0
        return ""


# 预编译：非流式场景一次性移除 </think> 块 + 压缩多余空行
_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)
_MULTI_NL_RE = re.compile(r"\n{3,}")


def strip_thinking(content: str) -> str:
    """非流式场景：移除所有 <think>...</think> 块，并压缩连续空行"""
    text = _THINK_RE.sub("", content)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


class ChatMessage(TypedDict):
    role: str  # system/user/assistant
    content: str


class ChatResult(TypedDict):
    content: str
    provider: str  # "spark" | "deepseek"
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    tool_calls: list[dict] | None  # Function Calling 结果 [{name, arguments: dict}]


def parse_tool_calls(message: dict) -> list[dict] | None:
    """从 OpenAI 兼容响应的 message 中解析 tool_calls。

    返回 [{name, arguments: dict}]，无 tool_calls 时返回 None。
    """
    import json

    raw = message.get("tool_calls") or []
    calls: list[dict] = []
    for tc in raw:
        fn = tc.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        arguments = fn.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except (json.JSONDecodeError, ValueError):
                arguments = {}
        calls.append({"name": name, "arguments": arguments})
    return calls or None


class LLMProvider(Protocol):
    """LLM Provider 协议"""

    name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        functions: list[dict] | None = None,
        request_id: str,
        scene: str,
    ) -> ChatResult: ...

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 8192,
        request_id: str,
        scene: str,
    ) -> AsyncIterator[dict]: ...
