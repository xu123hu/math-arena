"""Embedding Provider（providers/embedding.py）

BGE-M3 本地服务化调用，1024 维向量输出。
服务地址从配置读取（默认 localhost:8080）。
"""

import time

import httpx
import structlog

from app.config import settings
from app.providers.http import get_http

logger = structlog.get_logger()


class EmbeddingProvider:
    """BGE-M3 本地 Embedding 服务"""

    name: str = "embedding"

    def __init__(self) -> None:
        self._base_url = settings.embedding_base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._base_url)

    async def embed(
        self,
        texts: list[str],
        *,
        request_id: str = "",
    ) -> list[list[float]]:
        """将文本列表转换为 1024 维向量列表"""
        if not self.available:
            raise RuntimeError("Embedding service URL not configured")

        log = logger.bind(request_id=request_id, provider="embedding")
        log.info("embedding.start", text_count=len(texts))
        t0 = time.monotonic()

        client = get_http()
        try:
            resp = await client.post(
                f"{self._base_url}/v1/embeddings",
                json={
                    "model": "bge-m3",
                    "input": texts,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()

            # 兼容 OpenAI embeddings 格式
            embeddings = [item["embedding"] for item in data["data"]]
            latency = int((time.monotonic() - t0) * 1000)

            log.info("embedding.ok", latency_ms=latency, vector_dim=len(embeddings[0]) if embeddings else 0)
            return embeddings
        except httpx.HTTPStatusError as e:
            latency = int((time.monotonic() - t0) * 1000)
            log.error("embedding.http_error", status=e.response.status_code, latency_ms=latency)
            raise
        except Exception:
            latency = int((time.monotonic() - t0) * 1000)
            log.exception("embedding.error", latency_ms=latency)
            raise

    async def health_check(self) -> dict:
        """探测 Embedding 服务可用性"""
        if not self.available:
            return {"ok": False, "latency_ms": 0, "error": "Service not configured"}

        t0 = time.monotonic()
        client = get_http()
        try:
            resp = await client.post(
                f"{self._base_url}/v1/embeddings",
                json={
                    "model": "bge-m3",
                    "input": ["health"],
                },
                timeout=5.0,
            )
            resp.raise_for_status()
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": True, "latency_ms": latency}
        except Exception as e:
            latency = int((time.monotonic() - t0) * 1000)
            return {"ok": False, "latency_ms": latency, "error": str(e)[:200]}
