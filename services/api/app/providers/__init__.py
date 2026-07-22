# Providers - 模型服务层
# spark / deepseek / embedding / reranker / router
# 唯一允许碰星火/DeepSeek SDK 的地方

from app.providers.base import ChatMessage, ChatResult, LLMProvider
from app.providers.deepseek import DeepSeekProvider
from app.providers.spark import SparkProvider
from app.providers.embedding import EmbeddingProvider
from app.providers.router import ModelRouter, get_model_router, get_spark, get_deepseek
from app.providers.http import get_http, close_http

__all__ = [
    "ChatMessage",
    "ChatResult",
    "LLMProvider",
    "DeepSeekProvider",
    "SparkProvider",
    "EmbeddingProvider",
    "ModelRouter",
    "get_model_router",
    "get_spark",
    "get_deepseek",
    "get_http",
    "close_http",
]
