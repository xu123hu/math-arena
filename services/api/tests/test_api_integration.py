"""API 集成测试

使用 httpx.AsyncClient 测试完整 API 流程。
需要 PostgreSQL、Redis 运行中，且 DeepSeek API Key 可用。
"""

import json
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.main import app
from app.models.database import get_db


def _make_test_engine():
    """创建测试用 NullPool engine —— 每次连接独立，无跨循环问题"""
    return create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )


_test_engine = _make_test_engine()
_test_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


async def _override_get_db():
    """测试用 get_db 覆盖 —— NullPool 每次请求独立连接"""
    async with _test_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture
async def client():
    """创建测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ========== 健康检查 ==========


class TestHealthEndpoints:
    """健康检查端点测试"""

    async def test_health(self, client):
        """GET /api/health → 200"""
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_model_health(self, client):
        """GET /api/health/models → 200, 包含三通道"""
        resp = await client.get("/api/health/models")
        assert resp.status_code == 200
        data = resp.json()
        assert "spark" in data
        assert "deepseek" in data
        assert "embedding" in data
        # Verify response structure
        assert "ok" in data["deepseek"]
        assert "latency_ms" in data["deepseek"]
        # Skip ok=True assertion when DeepSeek API is unavailable
        # (e.g. CI without API key)
        if not data["deepseek"]["ok"]:
            pytest.skip("DeepSeek API not available in this environment")


# ========== 认证流程 ==========


class TestAuthFlow:
    """认证完整流程测试"""

    async def test_send_sms_code(self, client):
        """POST /api/auth/sms-code → 200"""
        import uuid as _uuid

        phone = f"138{_uuid.uuid4().int % 100000000:08d}"
        resp = await client.post("/api/auth/sms-code", json={"phone": phone})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    async def test_send_sms_code_invalid_phone(self, client):
        """无效手机号 → 422"""
        resp = await client.post("/api/auth/sms-code", json={"phone": "123"})
        assert resp.status_code == 422

    async def test_login_with_correct_code(self, client):
        """正确验证码登录 → 200, 获取 token"""
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        # 先发送验证码
        await client.post("/api/auth/sms-code", json={"phone": phone})
        # 登录（开发环境固定验证码 123456）
        resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "token" in data["data"]
        assert data["data"]["user"]["is_new"] is True
        assert data["data"]["user"]["active_role"] == "student"

    async def test_login_wrong_code(self, client):
        """错误验证码登录 → 验证码错误"""
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        # 先发送验证码
        await client.post("/api/auth/sms-code", json={"phone": phone})
        resp = await client.post("/api/auth/login", json={"phone": phone, "code": "000000"})
        data = resp.json()
        assert data["code"] != 0

    async def test_login_no_code_sent(self, client):
        """未发送验证码就登录 → 验证码已过期"""
        phone = f"139{str(uuid.uuid4().int)[:8]}"
        resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        data = resp.json()
        assert data["code"] != 0

    async def test_me_endpoint(self, client):
        """GET /api/auth/me → 200, 返回用户信息"""
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        # 登录获取 token
        await client.post("/api/auth/sms-code", json={"phone": phone})
        login_resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        token = login_resp.json()["data"]["token"]

        # 调用 /me
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["active_role"] == "student"

    async def test_me_without_auth(self, client):
        """未认证访问 /me → 401"""
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    async def test_role_switch(self, client):
        """POST /api/auth/role/switch → 换发 token"""
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        await client.post("/api/auth/sms-code", json={"phone": phone})
        login_resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        token = login_resp.json()["data"]["token"]

        # 切换到 student（默认角色，应该成功）
        resp = await client.post(
            "/api/auth/role/switch",
            json={"role": "student"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "token" in data["data"]

    async def test_role_switch_unauthorized(self, client):
        """未认证切换角色 → 401"""
        resp = await client.post("/api/auth/role/switch", json={"role": "student"})
        assert resp.status_code == 401


# ========== Agent 流程 ==========


class TestAgentFlow:
    """Agent 完整流程测试"""

    @pytest_asyncio.fixture
    async def auth_client(self, client):
        """已认证的客户端"""
        phone = f"138{str(uuid.uuid4().int)[:8]}"
        await client.post("/api/auth/sms-code", json={"phone": phone})
        login_resp = await client.post("/api/auth/login", json={"phone": phone, "code": "123456"})
        token = login_resp.json()["data"]["token"]
        return client, token, phone

    async def test_create_conversation(self, auth_client):
        """POST /api/agent/conversations → 200"""
        client, token, _ = auth_client
        resp = await client.post(
            "/api/agent/conversations",
            json={"title": "测试会话"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "id" in data["data"]
        assert data["data"]["title"] == "测试会话"

    async def test_list_conversations(self, auth_client):
        """GET /api/agent/conversations → 200"""
        client, token, _ = auth_client
        # 先创建一个会话
        await client.post(
            "/api/agent/conversations",
            json={"title": "列表测试"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # 获取列表
        resp = await client.get(
            "/api/agent/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "items" in data["data"]
        assert data["data"]["total"] >= 1

    async def test_chat_sse_flow(self, auth_client):
        """POST /api/agent/chat → SSE 流式响应"""
        client, token, _ = auth_client
        client_msg_id = str(uuid.uuid4())

        resp = await client.post(
            "/api/agent/chat",
            json={
                "content": "1+1等于多少？",
                "clientMsgId": client_msg_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # 解析 SSE 事件
        text = resp.text
        events = []
        for line in text.split("\n"):
            if line.startswith("event: "):
                events.append(line[7:])

        # 至少包含 meta 事件
        assert len(events) > 0
        assert "meta" in events

    async def test_chat_and_get_messages(self, auth_client):
        """发消息后获取历史消息"""
        client, token, _ = auth_client
        client_msg_id = str(uuid.uuid4())

        # 发送消息（会创建新会话）
        chat_resp = await client.post(
            "/api/agent/chat",
            json={
                "content": "什么是勾股定理？",
                "clientMsgId": client_msg_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert chat_resp.status_code == 200

        # 从 SSE meta 事件提取 conversation_id
        text = chat_resp.text
        conversation_id = None
        for line in text.split("\n"):
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if data.get("type") == "meta":
                        conversation_id = data["data"]["conversation_id"]
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

        assert conversation_id is not None

        # 获取历史消息
        msg_resp = await client.get(
            f"/api/agent/conversations/{conversation_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert msg_resp.status_code == 200
        msg_data = msg_resp.json()
        assert msg_data["code"] == 0
        items = msg_data["data"]["items"]
        assert len(items) >= 1  # 至少有用户消息

    async def test_conversations_unauthorized(self, client):
        """未认证访问会话列表 → 401"""
        resp = await client.get("/api/agent/conversations")
        assert resp.status_code == 401

    async def test_chat_unauthorized(self, client):
        """未认证聊天 → 401"""
        resp = await client.post(
            "/api/agent/chat",
            json={"content": "hi", "clientMsgId": "test-123"},
        )
        assert resp.status_code == 401
