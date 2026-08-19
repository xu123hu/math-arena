"""RAG 向量检索使用 system_configs["embedding"] 配置（阶段 5b P0 修复）

回归红线：kernel/rag.py 的 EmbeddingProvider 构造必须使用经
resolve_embedding_config(db) 解析的配置（env ← system_configs["embedding"]），
不得无参构造绕过库内配置。

配置解析时机：retrieve() 在并行任务启动前串行解析（复用调用方 session），
再传入 _embedding_available/_vector_search —— 避免共享 session 上并发
begin_nested()（SAVEPOINT）与 trgm/kp 查询冲突（阶段 5b 修复）。
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.kernel import rag as rag_module
from app.providers.embedding import EmbeddingConfig

_RESOLVED = EmbeddingConfig(
    provider="aliyun",
    base_url="",
    api_key="sk-rag",
    model="text-embedding-v4",
    dimension=1024,
    source="system",
)


@pytest.fixture
def patch_embedding(monkeypatch):
    """替换 providers.embedding 的 EmbeddingProvider/resolve_embedding_config，
    返回 (构造入参列表, resolve_embedding_config mock)"""
    import app.providers.embedding as embedding_module

    constructed: list = []
    resolve_mock = AsyncMock(return_value=_RESOLVED)

    class FakeProvider:
        def __init__(self, config=None):
            constructed.append(config)

        async def health_check(self):
            return {"ok": True}

        async def embed(self, texts, **kwargs):
            return [[0.1] * 4]

    monkeypatch.setattr(embedding_module, "EmbeddingProvider", FakeProvider)
    monkeypatch.setattr(embedding_module, "resolve_embedding_config", resolve_mock)
    return constructed, resolve_mock


async def test_embedding_available_uses_passed_config(patch_embedding):
    """可用性探测必须使用调用方传入的配置（不得在方法内再次 resolve）"""
    constructed, resolve_mock = patch_embedding
    pipeline = rag_module.RAGPipeline()
    ok = await pipeline._embedding_available(_RESOLVED)
    assert ok is True
    assert constructed, "EmbeddingProvider 必须被构造"
    assert constructed[0] is _RESOLVED, "必须使用调用方传入的配置"
    assert resolve_mock.call_count == 0, "配置由调用方解析，方法内不得再次 resolve"


async def test_vector_search_uses_passed_config(patch_embedding):
    """向量召回必须使用调用方传入的配置（不得在方法内再次 resolve）"""
    constructed, resolve_mock = patch_embedding
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    pipeline = rag_module.RAGPipeline()
    chunks = await pipeline._vector_search("函数", db, embedding_cfg=_RESOLVED)

    assert chunks == []
    assert constructed, "EmbeddingProvider 必须被构造"
    assert all(c is _RESOLVED for c in constructed), (
        "所有 EmbeddingProvider 构造都必须使用调用方传入的配置"
    )
    assert resolve_mock.call_count == 0, "配置由调用方解析，方法内不得再次 resolve"


async def test_retrieve_resolves_config_once_serially(patch_embedding, monkeypatch):
    """retrieve() 必须在并行任务启动前串行解析配置一次，并流入向量路"""
    constructed, resolve_mock = patch_embedding
    db = MagicMock()
    db.execute.return_value.all.return_value = []

    async def _empty(*args, **kwargs):
        return []

    monkeypatch.setattr(rag_module.RAGPipeline, "_trgm_search", _empty)
    monkeypatch.setattr(rag_module.RAGPipeline, "_kp_tag_search", _empty)
    monkeypatch.setattr(
        "app.providers.cloud_kb.resolve_cloud_kb_config", AsyncMock(return_value=None)
    )

    @asynccontextmanager
    async def _mock_session():
        yield db

    monkeypatch.setattr(rag_module, "async_session_factory", _mock_session)

    pipeline = rag_module.RAGPipeline()
    result = await pipeline.retrieve("函数", db=db, conversation_history=[])

    assert result.answerable is False  # 各路空 → no_knowledge
    assert resolve_mock.call_count == 1, "配置解析必须只发生一次（串行，并行任务启动前）"
    assert constructed and constructed[0] is _RESOLVED, "配置必须流入向量路"
