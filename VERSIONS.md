# Math Arena - 版本锁定表
# 任何环境不一致先对表，禁止"我机器上能跑"

## 前端

| 包 | 锁定版本 | 说明 |
|---|---|---|
| vue | ^3.4 | 前端框架 |
| typescript | ^5.4 | 类型系统 |
| vite | ^5 | 构建工具 |
| element-plus | ^2.7 | UI 组件库（PC 优先） |
| katex | ^0.16 | 公式渲染 |
| echarts | ^5.5 | 图表（M2） |
| pinia | ^2.1 | 状态管理 |
| @microsoft/fetch-event-source | ^0.5 | SSE 客户端（POST，禁用原生 EventSource） |
| markdown-it | latest | Markdown 渲染 |
| @vscode/markdown-it-katex | latest | KaTeX 插件 |
| dompurify | latest | XSS 过滤 |

## 后端

| 包 | 锁定版本 | 说明 |
|---|---|---|
| python | ^3.11 | 运行时 |
| fastapi | ^0.110 | Web 框架 |
| pydantic | ^2.6 | 数据校验 |
| pydantic-settings | latest | 配置管理 |
| sqlalchemy[asyncio] | ^2.0 | ORM（async） |
| asyncpg | latest | PostgreSQL 异步驱动 |
| alembic | latest | 数据库迁移 |
| httpx | latest | HTTP 客户端（模型调用） |
| redis | ^5.0 | 缓存/限流 |
| pgvector | latest | 向量类型 |
| structlog | latest | 结构化日志 |
| uvicorn[standard] | latest | ASGI 服务器 |
| pytest | latest | 测试框架 |
| pytest-asyncio | latest | 异步测试 |
| ruff | latest | Linter |
| black | latest | Formatter |
| mypy | latest | 类型检查 |

## 基础设施

| 服务 | 版本 | 说明 |
|---|---|---|
| PostgreSQL | 15 | 主数据库 + pgvector 扩展 |
| Redis | 7 | 缓存/限流 |
| MinIO | latest | 对象存储（M2） |

## AI 服务

| 服务 | 模型 | 说明 |
|---|---|---|
| 星火大模型 | spark-ultra | 主通道（HTTP 协议，禁止 WebSocket） |
| DeepSeek | deepseek-v4-flash | 备用通道（OpenAI 兼容接口） |
| BGE-M3 | - | Embedding（1024 维，本地服务化） |
| bge-reranker | - | Reranker（本地服务化） |
