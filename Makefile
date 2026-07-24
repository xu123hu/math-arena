.PHONY: help dev dev-db docker-up docker-down migrate migrate-down test eval lint lint-fix clean

help: ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ==================== 开发 ====================

dev: ## 本地开发启动后端（uvicorn）
	cd services/api && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-db: ## 只启动 postgres + redis
	docker compose -f deploy/docker-compose.yml up -d postgres redis

docker-up: ## 启动全部 Docker 服务
	docker compose -f deploy/docker-compose.yml up -d

docker-down: ## 停止全部 Docker 服务
	docker compose -f deploy/docker-compose.yml down

# ==================== 数据库 ====================

migrate: ## 运行数据库迁移（alembic upgrade head）
	cd services/api && alembic upgrade head

migrate-down: ## 回退一步迁移
	cd services/api && alembic downgrade -1

# ==================== 代码质量 ====================

lint: ## 运行 lint 检查（ruff + black）
	cd services/api && ruff check .
	cd services/api && black --check .

lint-fix: ## 自动修复 lint 问题
	cd services/api && ruff check --fix .
	cd services/api && black .

# ==================== 测试 ====================

test: ## 运行后端测试
	cd services/api && pytest

eval: ## 运行 M1 评测（router_30 + rag_30，走真实 LLM 路径）
	cd services/api && python -m eval.run_eval --all

# ==================== 清理 ====================

clean: ## 清理构建产物和缓存
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
