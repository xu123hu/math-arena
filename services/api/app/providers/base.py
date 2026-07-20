"""模型服务层协议（providers/base.py）

所有模型调用都走这里，禁止在别处直连模型。
"""
from typing import AsyncIterator, Protocol, TypedDict


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


class LLMProvider(Protocol):
    """LLM Provider 协议"""

    name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        functions: list[dict] | None = None,
        request_id: str,
        scene: str,
    ) -> ChatResult: ...

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        request_id: str,
        scene: str,
    ) -> AsyncIterator[str]: ...
