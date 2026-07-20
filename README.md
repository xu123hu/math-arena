# Math Arena 🎓

数学垂类大模型 —— 面向高中数学的教学科研智能体平台

## 项目概述

Math Arena 是一个基于大语言模型的数学学科垂直领域智能助手平台，面向三类用户：

- **学生**：与 AI 聊天学习数学，基于教材知识库给出带引用的回答
- **教师**：建班管理，查看学生学习情况
- **科研人员**：科研辅助对话（M1 占位，M4 完善）

### 核心特性

- 🔍 **RAG 增强**：基于教材知识库的检索增强生成，回答带真实引用
- 📐 **公式渲染**：KaTeX 实时渲染数学公式，支持流式逐段升级
- 🧠 **记忆系统**：滚动摘要 + 指代消解，支持多轮连续对话
- 🔄 **双模型降级**：星火主通道 + DeepSeek-v4-flash 备用，用户无感知切换
- 📚 **班级管理**：教师建班发码、学生加码入班、待确认流程

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Element Plus + KaTeX |
| 后端 | FastAPI + SQLAlchemy 2.x (async) + Pydantic v2 |
| 数据库 | PostgreSQL 15 + pgvector + pg_trgm |
| 缓存 | Redis 7 |
| AI 模型 | 星火大模型 (主) + DeepSeek-v4-flash (备) |
| 部署 | Docker Compose |

## 仓库结构

```
math-arena/
├── apps/
│   └── web/                      # Vue 3 前端
├── packages/
│   └── protocol/                 # 前后端共享协议（类型定义）
├── services/
│   ├── api/                      # FastAPI 后端
│   └── sandbox/                  # SymPy 沙箱（M2）
├── deploy/                       # Docker Compose 部署配置
├── docs/                         # 文档与验收材料
└── README.md
```

## 快速开始

### 前置要求

- Node.js >= 20 + pnpm >= 9
- Python >= 3.11
- Docker & Docker Compose
- PostgreSQL 15（或通过 Docker）
- Redis 7（或通过 Docker）

### 方式一：Docker Compose 一键启动（推荐）

```bash
# 克隆仓库
git clone https://github.com/xu123hu/math-arena.git
cd math-arena

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际密钥

# 一键启动全栈
docker compose -f deploy/docker-compose.yml up -d

# 访问
# 前端：http://localhost:5173
# 后端 API：http://localhost:8000
# API 文档：http://localhost:8000/docs
```

### 方式二：本地开发

#### 后端

```bash
cd services/api

# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux

# 安装依赖
pip install -e ".[dev]"

# 数据库迁移
alembic upgrade head

# 启动后端
uvicorn app.main:app --reload --port 8000
```

#### 前端

```bash
# 在项目根目录
pnpm install

# 启动前端开发服务器
pnpm dev:web
```

### 验证安装

```bash
# 检查后端健康
curl http://localhost:8000/api/health

# 检查模型通道
curl http://localhost:8000/api/health/models
```

## Git 工作流

### 分支策略

| 分支 | 用途 | 保护规则 |
|---|---|---|
| `main` | 生产就绪代码 | 只接受 PR，需 review + CI 绿 |
| `feat/<domain>-<desc>` | 功能开发 | 如 `feat/kernel-router` |
| `fix/<desc>` | Bug 修复 | 如 `fix/sse-reconnect` |

### Commit 规范

采用 [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(kernel): 实现意图路由 L2 层
fix(auth): 修复验证码过期后仍可登录的问题
docs(api): 更新 SSE 事件协议文档
chore(ci): 添加后端 lint 检查
```

### 提交 PR 前检查

- [ ] `pnpm build` 通过
- [ ] `pnpm lint` 0 error
- [ ] 后端 `ruff check .` + `mypy --strict app/kernel/` 通过
- [ ] 测试通过
- [ ] 改协议时同步更新 `packages/protocol` 和文档

## 开发文档

所有开发文档位于 `docs/` 目录：

- 技术开发手册 v2.0
- 后端开发指引
- 前端开发指引
- API 接口文档
- 联调与验收清单
- 数据库开发指引

## 团队分工

| 角色 | 职责 |
|---|---|
| 技术组长 | 后端核心开发、架构设计、进度协调 |
| 前端开发 | Vue 3 前端实现、交互体验 |
| 协助人员 | 测试、文档、素材准备 |

## License

Private - 仅限团队内部使用
