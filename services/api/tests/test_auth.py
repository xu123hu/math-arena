"""Auth 单元测试

测试 JWT 签发/验证、验证码流程、登录、角色切换。
"""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from jose import jwt

from app.config import settings
from app.gateway.jwt import create_access_token, create_token_with_role, decode_token

# ========== JWT 测试 ==========


class TestJWT:
    """JWT 签发和验证测试"""

    def test_create_access_token(self):
        """创建 access token 包含正确数据"""
        data = {"sub": "test-user-id", "role": "student"}
        token = create_access_token(data)
        decoded = decode_token(token)
        assert decoded["sub"] == "test-user-id"
        assert decoded["role"] == "student"
        assert "exp" in decoded

    def test_create_access_token_custom_expiry(self):
        """自定义过期时间"""
        data = {"sub": "test-user-id"}
        token = create_access_token(data, expires_delta=timedelta(hours=1))
        decoded = decode_token(token)
        assert decoded["sub"] == "test-user-id"
        assert "exp" in decoded

    def test_create_token_with_role(self):
        """创建包含角色信息的 token"""
        user_id = str(uuid.uuid4())
        token = create_token_with_role(
            user_id=user_id,
            role="student",
            roles=["student", "teacher"],
            verified=True,
        )
        decoded = decode_token(token)
        assert decoded["sub"] == user_id
        assert decoded["active_role"] == "student"
        assert decoded["roles"] == ["student", "teacher"]
        assert decoded["verified"] is True

    def test_create_token_default_roles(self):
        """默认 roles 列表包含当前角色"""
        user_id = str(uuid.uuid4())
        token = create_token_with_role(user_id=user_id, role="teacher")
        decoded = decode_token(token)
        assert decoded["roles"] == ["teacher"]

    def test_decode_invalid_token_raises(self):
        """无效 token 解码抛出异常"""
        from jose import JWTError

        with pytest.raises(JWTError):
            decode_token("invalid.token.here")

    def test_decode_expired_token_raises(self):
        """过期 token 解码抛出异常"""
        from jose import JWTError

        data = {"sub": "test-user-id"}
        token = create_access_token(data, expires_delta=timedelta(seconds=-1))
        with pytest.raises(JWTError):
            decode_token(token)

    def test_token_uses_configured_algorithm(self):
        """token 使用配置的算法"""
        token = create_access_token({"sub": "test"})
        # 验证头部算法
        header = jwt.get_unverified_header(token)
        assert header["alg"] == settings.jwt_algorithm


# ========== 验证码 Redis 工具测试 ==========


class TestRedisUtils:
    """Redis 验证码工具测试（mock Redis）"""

    async def test_set_and_get_sms_code(self):
        """设置和获取验证码"""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value="123456")

        with patch("app.gateway.redis.get_redis", return_value=mock_redis):
            from app.gateway.redis import get_sms_code, set_sms_code

            await set_sms_code("13800138000", "123456")
            mock_redis.set.assert_called_once()

            code = await get_sms_code("13800138000")
            assert code == "123456"

    async def test_delete_sms_code(self):
        """删除验证码"""
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.gateway.redis.get_redis", return_value=mock_redis):
            from app.gateway.redis import delete_sms_code

            await delete_sms_code("13800138000")
            mock_redis.delete.assert_called_once()

    async def test_check_sms_rate_limit_first_time(self):
        """首次发送验证码，频率检查通过"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=False)
        mock_redis.set = AsyncMock()

        with patch("app.gateway.redis.get_redis", return_value=mock_redis):
            from app.gateway.redis import check_sms_rate_limit

            result = await check_sms_rate_limit("13800138000")
            assert result is True

    async def test_check_sms_rate_limit_too_fast(self):
        """频率过快，返回 False"""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=True)

        with patch("app.gateway.redis.get_redis", return_value=mock_redis):
            from app.gateway.redis import check_sms_rate_limit

            result = await check_sms_rate_limit("13800138000")
            assert result is False


# ========== Auth 依赖测试 ==========


class TestAuthDependency:
    """认证依赖注入测试"""

    async def test_get_current_user_no_credentials(self):
        """无凭据时抛出 401"""
        from fastapi import HTTPException

        from app.gateway.auth import get_current_user

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(None)
        assert exc_info.value.status_code == 401

    async def test_get_current_user_invalid_token(self):
        """无效 token 抛出 401"""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.gateway.auth import get_current_user

        creds = HTTPAuthorizationCredentials(credentials="invalid.token.here", scheme="Bearer")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(creds)
        assert exc_info.value.status_code == 401

    async def test_get_current_user_valid_token(self):
        """有效 token 返回用户信息"""
        from fastapi.security import HTTPAuthorizationCredentials

        from app.gateway.auth import get_current_user

        user_id = str(uuid.uuid4())
        token = create_token_with_role(user_id=user_id, role="student")
        creds = HTTPAuthorizationCredentials(credentials=token, scheme="Bearer")
        result = await get_current_user(creds)
        assert result["sub"] == user_id
        assert result["active_role"] == "student"
        assert "student" in result["roles"]

    async def test_get_current_user_no_sub(self):
        """token 无 sub 字段时 401"""
        from fastapi import HTTPException
        from fastapi.security import HTTPAuthorizationCredentials

        from app.gateway.auth import get_current_user

        token = create_access_token({"role": "student"})
        creds = HTTPAuthorizationCredentials(credentials=token, scheme="Bearer")
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(creds)
        assert exc_info.value.status_code == 401
