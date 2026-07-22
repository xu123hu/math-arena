"""Provider 单元测试

测试 DeepSeekProvider、SparkProvider 和 ModelRouter。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.providers.base import ChatResult
from app.providers.deepseek import DeepSeekProvider
from app.providers.router import ModelRouter
from app.providers.spark import SparkProvider

# ========== DeepSeekProvider 测试 ==========


class TestDeepSeekProvider:
    """DeepSeekProvider 单元测试"""

    def test_available_with_key(self):
        """有 API Key 时 available=True"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            assert provider.available is True

    def test_available_without_key(self):
        """无 API Key 时 available=False"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = ""
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            assert provider.available is False

    async def test_health_check_no_key(self):
        """无 Key 时 health_check 返回 ok=False"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = ""
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            result = await provider.health_check()
            assert result["ok"] is False
            assert "not configured" in result["error"]

    async def test_health_check_success(self):
        """health_check 成功时返回 ok=True"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False

            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            with patch("app.providers.deepseek.get_http", return_value=mock_client):
                provider = DeepSeekProvider()
                result = await provider.health_check()
                assert result["ok"] is True
                assert result["model"] == "deepseek-v4-flash"
                assert "latency_ms" in result

    async def test_health_check_failure(self):
        """health_check 失败时返回 ok=False"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            with patch("app.providers.deepseek.get_http", return_value=mock_client):
                provider = DeepSeekProvider()
                result = await provider.health_check()
                assert result["ok"] is False
                assert "error" in result

    async def test_chat_no_key_raises(self):
        """无 Key 时 chat 抛出 RuntimeError"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = ""
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            with pytest.raises(RuntimeError, match="API key not configured"):
                await provider.chat(
                    [{"role": "user", "content": "hi"}],
                    request_id="test",
                    scene="chat",
                )

    async def test_chat_success(self):
        """chat 成功返回 ChatResult"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False

            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Hello!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)

            with patch("app.providers.deepseek.get_http", return_value=mock_client):
                provider = DeepSeekProvider()
                result = await provider.chat(
                    [{"role": "user", "content": "hi"}],
                    request_id="test-1",
                    scene="chat",
                )
                assert result["content"] == "Hello!"
                assert result["provider"] == "deepseek"
                assert result["input_tokens"] == 10
                assert result["output_tokens"] == 5

    def test_build_payload_thinking_disabled(self):
        """thinking=False 时 payload 包含 extra_body"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            payload = provider._build_payload([{"role": "user", "content": "hi"}])
            assert "extra_body" in payload
            assert payload["extra_body"]["thinking"]["type"] == "disabled"

    def test_build_payload_with_functions(self):
        """传入 functions 时 payload 包含 tools"""
        with patch("app.providers.deepseek.settings") as mock_settings:
            mock_settings.deepseek_api_key = "test-key"
            mock_settings.deepseek_model = "deepseek-v4-flash"
            mock_settings.deepseek_thinking = False
            provider = DeepSeekProvider()
            funcs = [{"name": "test_func", "description": "A test function"}]
            payload = provider._build_payload([{"role": "user", "content": "hi"}], functions=funcs)
            assert "tools" in payload
            assert payload["tools"][0]["type"] == "function"


# ========== SparkProvider 测试 ==========


class TestSparkProvider:
    """SparkProvider 单元测试"""

    def test_available_with_password(self):
        """有 API password 时 available=True"""
        with patch("app.providers.spark.settings") as mock_settings:
            mock_settings.spark_api_password = "test-password"
            mock_settings.spark_model = "spark-ultra"
            provider = SparkProvider()
            assert provider.available is True

    def test_available_without_password(self):
        """无 API password 时 available=False"""
        with patch("app.providers.spark.settings") as mock_settings:
            mock_settings.spark_api_password = ""
            mock_settings.spark_model = "spark-ultra"
            provider = SparkProvider()
            assert provider.available is False

    async def test_health_check_no_password(self):
        """无 password 时 health_check 返回 ok=False"""
        with patch("app.providers.spark.settings") as mock_settings:
            mock_settings.spark_api_password = ""
            mock_settings.spark_model = "spark-ultra"
            provider = SparkProvider()
            result = await provider.health_check()
            assert result["ok"] is False
            assert "not configured" in result["error"]


# ========== ModelRouter 测试 ==========


class TestModelRouter:
    """ModelRouter 降级逻辑测试"""

    async def test_spark_success_no_fallback(self):
        """星火成功时不降级"""
        spark = MagicMock(spec=SparkProvider)
        spark.available = True
        spark.chat = AsyncMock(
            return_value=ChatResult(
                content="spark response",
                provider="spark",
                model="spark-ultra",
                input_tokens=10,
                output_tokens=20,
                latency_ms=100,
            )
        )

        deepseek = MagicMock(spec=DeepSeekProvider)
        deepseek.chat = AsyncMock()

        router = ModelRouter(spark=spark, deepseek=deepseek)
        result = await router.chat(
            [{"role": "user", "content": "hi"}],
            request_id="test",
            scene="chat",
        )
        assert result["content"] == "spark response"
        assert result["provider"] == "spark"
        deepseek.chat.assert_not_called()

    async def test_spark_fail_fallback_to_deepseek(self):
        """星火失败时降级到 DeepSeek"""
        spark = MagicMock(spec=SparkProvider)
        spark.available = True
        spark.chat = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        deepseek = MagicMock(spec=DeepSeekProvider)
        deepseek.chat = AsyncMock(
            return_value=ChatResult(
                content="deepseek response",
                provider="deepseek",
                model="deepseek-v4-flash",
                input_tokens=10,
                output_tokens=15,
                latency_ms=200,
            )
        )

        router = ModelRouter(spark=spark, deepseek=deepseek)
        result = await router.chat(
            [{"role": "user", "content": "hi"}],
            request_id="test",
            scene="chat",
        )
        assert result["content"] == "deepseek response"
        assert result["provider"] == "deepseek"

    async def test_spark_unavailable_skip_to_deepseek(self):
        """星火不可用时直接走 DeepSeek"""
        spark = MagicMock(spec=SparkProvider)
        spark.available = False

        deepseek = MagicMock(spec=DeepSeekProvider)
        deepseek.chat = AsyncMock(
            return_value=ChatResult(
                content="deepseek only",
                provider="deepseek",
                model="deepseek-v4-flash",
                input_tokens=5,
                output_tokens=10,
                latency_ms=150,
            )
        )

        router = ModelRouter(spark=spark, deepseek=deepseek)
        result = await router.chat(
            [{"role": "user", "content": "hi"}],
            request_id="test",
            scene="chat",
        )
        assert result["content"] == "deepseek only"
        spark.chat.assert_not_called()

    async def test_all_providers_fail(self):
        """所有 Provider 失败时抛出 RuntimeError"""
        spark = MagicMock(spec=SparkProvider)
        spark.available = True
        spark.chat = AsyncMock(side_effect=httpx.ConnectError("fail"))

        deepseek = MagicMock(spec=DeepSeekProvider)
        deepseek.chat = AsyncMock(side_effect=RuntimeError("also fail"))

        router = ModelRouter(spark=spark, deepseek=deepseek)
        with pytest.raises(RuntimeError, match="All model providers failed"):
            await router.chat(
                [{"role": "user", "content": "hi"}],
                request_id="test",
                scene="chat",
            )

    async def test_spark_5xx_fallback_to_deepseek(self):
        """星火 5xx 错误时降级到 DeepSeek"""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        spark = MagicMock(spec=SparkProvider)
        spark.available = True
        spark.chat = AsyncMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_resp)
        )

        deepseek = MagicMock(spec=DeepSeekProvider)
        deepseek.chat = AsyncMock(
            return_value=ChatResult(
                content="fallback ok",
                provider="deepseek",
                model="deepseek-v4-flash",
                input_tokens=5,
                output_tokens=10,
                latency_ms=100,
            )
        )

        router = ModelRouter(spark=spark, deepseek=deepseek)
        result = await router.chat(
            [{"role": "user", "content": "hi"}],
            request_id="test",
            scene="chat",
        )
        assert result["content"] == "fallback ok"
        assert result["provider"] == "deepseek"
