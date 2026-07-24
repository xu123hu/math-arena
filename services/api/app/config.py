"""应用配置管理（pydantic-settings）

所有密钥走环境变量，代码库出现密钥字符串 = 事故。
"""

from pathlib import Path

from pydantic_settings import BaseSettings

# .env 位于 monorepo 根目录（services/api 上溯两级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置，从环境变量 / .env 文件加载"""

    # -------------------- 数据库 --------------------
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/math_arena"

    # -------------------- Redis --------------------
    redis_url: str = "redis://localhost:6379/0"

    # -------------------- 星火大模型（主通道） --------------------
    spark_api_password: str = ""
    spark_model: str = "spark-ultra"

    # -------------------- DeepSeek（备用通道） --------------------
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_thinking: bool = False  # ADR-001-8: 聊天场景默认关思考
    deepseek_base_url: str = "https://api.xiaomimimo.com/v1/chat/completions"

    # -------------------- Embedding / Reranker --------------------
    embedding_base_url: str = "http://localhost:8080"
    reranker_base_url: str = "http://localhost:8081"

    # -------------------- RAG 阈值 --------------------
    rag_trgm_threshold: float = 0.08  # word_similarity 召回下限（短查询 vs 长文档）
    rag_raw_threshold: float = 0.15  # 降级路径拒答闸门（top 原始分低于此值 → 拒答）
    rag_refuse_threshold: float = 0.35  # reranker 生效时的拒答闸门

    # -------------------- JWT --------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # -------------------- 应用 --------------------
    app_env: str = "development"  # development / staging / production
    dev_sms_code: str = "123456"  # 开发环境固定验证码
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"  # 逗号分隔

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_production(self) -> None:
        """生产环境启动前校验，不安全配置直接拒绝启动"""
        if self.app_env == "production" and self.jwt_secret in (
            "change-me-in-production",
            "change-me-to-a-random-secret-in-production",
            "",
        ):
            raise RuntimeError("生产环境必须配置强随机 JWT_SECRET")

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
