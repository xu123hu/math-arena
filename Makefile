.PHONY: help dev dev-api dev-web build build-web lint test clean

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ==================== 开发 ====================

dev: ## 启动全栈开发（Docker Compose）
	docker compose -f deploy/docker-compose.yml up -d

dev-api: ## 启动后端开发服务器
	cd services/api && uvicorn app.main:app --reload --port 8000

dev-web: ## 启动前端开发服务器
	pnpm dev:web

# ==================== 构建 ====================

build: ## 构建所有包
	pnpm build

build-web: ## 构建前端
	pnpm build:web

# ==================== 代码质量 ====================

lint: ## 运行所有 lint 检查
	pnpm lint
	cd services/api && ruff check .

lint-fix: ## 自动修复 lint 问题
	cd services/api && ruff check --fix . && black .

type-check: ## 类型检查
	pnpm type-check
	cd services/api && mypy --strict app/kernel/

# ==================== 测试 ====================

test: ## 运行所有测试
	pnpm test
	cd services/api && pytest

test-api: ## 运行后端测试
	cd services/api && pytest -v

test-web: ## 运行前端测试
	pnpm test

eval: ## 运行 AI 评测集
	cd services/api && python -m pytest eval/

# ==================== 数据库 ====================

db-upgrade: ## 运行数据库迁移
	cd services/api && alembic upgrade head

db-downgrade: ## 回滚数据库迁移
	cd services/api && alembic downgrade base

db-revision: ## 创建新迁移（需要 MSG 参数）
	cd services/api && alembic revision --autogenerate -m "$(MSG)"

# ==================== 清理 ====================

clean: ## 清理构建产物和缓存
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".vite" -exec rm -rf {} + 2>/dev/null || true

# ==================== Docker ====================

docker-up: ## 启动 Docker 服务
	docker compose -f deploy/docker-compose.yml up -d

docker-down: ## 停止 Docker 服务
	docker compose -f deploy/docker-compose.yml down

docker-logs: ## 查看 Docker 日志
	docker compose -f deploy/docker-compose.yml logs -f

docker-build: ## 重新构建 Docker 镜像
	docker compose -f deploy/docker-compose.yml build
