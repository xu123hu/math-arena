"""应用配置管理（pydantic-settings）

所有密钥走环境变量，代码库出现密钥字符串 = 事故。
"""

from pydantic_settings import BaseSettings


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

    # -------------------- Embedding / Reranker --------------------
    embedding_base_url: str = "http://localhost:8080"
    reranker_base_url: str = "http://localhost:8081"

    # -------------------- JWT --------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # -------------------- 应用 --------------------
    app_env: str = "development"  # development / staging / production
    dev_sms_code: str = "123456"  # 开发环境固定验证码

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
