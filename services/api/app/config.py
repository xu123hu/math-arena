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
    spark_thinking: bool = False  # 思考模式全局默认（per-call thinking=True 可覆盖）

    # -------------------- DeepSeek（备用通道） --------------------
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_thinking: bool = False  # ADR-001-8: 聊天场景默认关思考
    deepseek_base_url: str = "https://api.xiaomimimo.com/v1/chat/completions"

    # -------------------- Embedding / Reranker --------------------
    embedding_base_url: str = "http://localhost:8080"
    reranker_base_url: str = "http://localhost:8081"
    embedding_provider: str = "local"  # local（本地服务）/ 远程 OpenAI 兼容服务
    embedding_api_key: str = ""  # 远程 embedding 服务凭证（local 时留空）
    embedding_model: str = "bge-m3"

    # -------------------- RAG 阈值 --------------------
    rag_trgm_threshold: float = 0.08  # word_similarity 召回下限（短查询 vs 长文档）
    # 降级路径拒答闸门（top 原始分低于此值 → 拒答）。
    # 2026-08-07 按 BGE-M3 全量 105 切片实测校准：书外查询 top 原始分 ≤0.43，
    # 书内查询 ≥0.48（典型 0.58~0.70），取 0.45 落分隔区间（原 0.15 为部分切片
    # 缺向量时期的手感值，向量全覆盖后过松，书外问题会漏闸）。
    rag_raw_threshold: float = 0.45
    rag_trgm_gate: float = 0.35  # trgm 路拒答闸门（wsim 量纲；精确文本命中典型 0.5+，书外查询通常无召回）
    rag_refuse_threshold: float = 0.35  # reranker 生效时的拒答闸门

    # -------------------- 云知识库（管理后台可热更新，env 为兜底层） --------------------
    cloud_kb_enabled: bool = False  # 总开关
    cloud_kb_provider: str = ""  # tencent_lkeap / aliyun_bailian / 空=未配置
    cloud_kb_config: str = "{}"  # JSON 兜底：provider 专属凭证（credentials/knowledge_base_id 等）
    cloud_kb_top_k: int = 5  # 检索召回条数
    cloud_kb_score_threshold: float = 0.5  # 相关性分数下限

    # -------------------- 对象存储（ADR-M2B-001：boto3 统一抽象，支持自定义端口） --------------------
    storage_provider: str = "cos"  # cos / oss / minio / s3_custom
    storage_scheme: str = "https"  # http / https
    storage_host: str = ""  # 如 cos.ap-guangzhou.myqcloud.com；空则按 provider+region 推导
    storage_port: int | None = None  # 自定义端口（私有部署/MinIO 常用）
    storage_endpoint_url: str = ""  # 完整 endpoint，给出时优先于 scheme/host/port 拼接
    storage_region: str = ""  # 如 ap-guangzhou / cn-hangzhou
    storage_bucket: str = ""  # COS 需带 -APPID 后缀
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_session_token: str = ""  # 可选，STS 临时凭证
    storage_presign_expires: int = 900  # 预签名 URL 有效期（秒）

    # -------------------- 星辰工作流（ADR-M2B-004：全配置化可移植） --------------------
    xingchen_enabled: bool = False  # 总开关
    xingchen_base_url: str = "https://xingchen-api.xf-yun.com"  # 可指私有化部署（含端口）
    xingchen_api_key: str = ""
    xingchen_api_secret: str = ""
    xingchen_flow_ids: str = "{}"  # JSON：flow 注册名 -> flow_id
    xingchen_timeouts: str = "{}"  # JSON：flow 注册名 -> read 超时秒（缺省用注册表默认）
    xingchen_max_concurrency: int = 3  # 全局并发信号量（星辰 QPS 1~3 硬约束）
    xingchen_queue_max: int = 10  # 排队上限，超过直接走本地降级
    xingchen_daily_alert_threshold: int = 1200  # 日调用量告警阈值（账号周期 1500 预留 20%）

    # -------------------- 讯飞语音（IAT 听写 + 长语音转写） --------------------
    xfyun_app_id: str = ""
    xfyun_api_key: str = ""  # IAT 听写
    xfyun_api_secret: str = ""  # IAT 听写签名
    xfyun_lfasr_secret_key: str = ""  # 长语音转写（F9 预处理）
    xfyun_iat_base_url: str = "https://iat-api.xfyun.cn/v2/iat"
    xfyun_lfasr_base_url: str = "https://raasr.xfyun.cn/v2/api"

    # -------------------- 联网搜索试点（默认关闭） --------------------
    web_search_enabled: bool = False

    # -------------------- 学情增长（M2 迭代16 第二批） --------------------
    # AI 管家化：永久开启 LLM 文案润色（任何异常/超时自动回退模板，零风险）
    growth_llm_polish: bool = True  # 鼓励语/错因文案 LLM 润色开关；关闭走模板，开启后异常/超时自动回退模板

    # -------------------- AI 管家（Butler Orchestrator，M2 迭代17） --------------------
    butler_llm_enabled: bool = True  # 管家 LLM 生成总开关（文案/推荐/路径）；关闭时全部走规则兜底
    butler_proactive_limit: int = 3  # 每日主动推送上限（防骚扰，today-3 + 复习提醒 + 鼓励）
    butler_dedup_hours: int = 8  # 同类事件去重窗口（小时），窗口内重复事件只推一次
    butler_polish_timeout_s: int = 10  # 管家 LLM 文案单次超时（秒），超时回退模板
    butler_polish_cache_ttl_s: int = 24 * 3600  # 管家文案缓存 TTL（秒）

    # -------------------- Butler Kernel v2（阶段 3C，默认关闭，保持旧内核） --------------------
    # enabled：仅"已迁移且有工具支持"的场景走 v2，未迁移场景继续旧内核；
    # shadow：v2 只做无副作用影子运行（WRITE/EXTERNAL 一律 shadow_skipped），结果不返回用户；
    # 真实领域工具迁移完成前，两个开关都应保持 false。
    butler_v2_enabled: bool = False
    butler_v2_shadow: bool = False

    # -------------------- Feature Profile（阶段 1：M2/M4 路由面隔离） --------------------
    # M2 默认不挂载科研端（F14 wf_verify_derivation）；M4 科研端置 true 后自动恢复。
    # 仅控制路由面与管理列表，不物理删除科研代码（research_router 始终存在）。
    m2_enable_research: bool = False

    # -------------------- M3 教师端（默认关闭，不干扰 M2） --------------------
    # M3_ENABLE_TEACHER=false：默认不挂载 /api/teacher/* 路由；测试 profile 可显式开启。
    m3_enable_teacher: bool = False

    # -------------------- SymPy 沙箱 --------------------
    sandbox_timeout_ms: int = 10000
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_limit_s: int = 10

    # -------------------- 服务间工具密钥（/tools/* 与运维端点） --------------------
    tool_api_key: str = ""  # X-Tool-Key；空则 /tools/* 全部 50301（未配置）

    # -------------------- 并发与限流（A9 配置化） --------------------
    sse_global_concurrency: int = 20  # SSE 全局并发上限
    sse_user_concurrency: int = 3  # SSE 每用户并发上限
    upload_rate_limit_per_hour: int = 10  # 每用户上传限流
    asr_token_rate_limit_per_hour: int = 20  # 每用户 asr-token 限流
    student_daily_practice_limit: int = 30  # 学生日刷题上限（防沉迷）

    # -------------------- JWT --------------------
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7
    auth_access_token_minutes: int = 15
    auth_allow_legacy_tokens: bool = True
    auth_sms_provider: str = "demo"
    auth_demo_sms_allowlist: str = "13800000000"
    auth_otp_pepper: str = "development-only-otp-pepper"
    auth_refresh_token_pepper: str = "development-only-refresh-token-pepper"
    auth_invite_pepper: str = "development-only-invite-pepper"
    auth_standard_absolute_hours: int = 168
    auth_standard_idle_minutes: int = 1440
    auth_remember_absolute_hours: int = 720
    auth_remember_idle_minutes: int = 10080
    auth_admin_absolute_hours: int = 12
    auth_admin_idle_minutes: int = 30
    auth_trusted_proxies: str = ""
    auth_captcha_provider: str = "disabled"
    auth_break_glass_enabled: bool = False
    auth_trusted_operations_env: bool = False
    auth_break_glass_secret: str = ""
    tencent_sms_secret_id: str = ""
    tencent_sms_secret_key: str = ""
    tencent_sms_sdk_app_id: str = ""
    tencent_sms_sign_name: str = ""
    tencent_sms_template_id: str = ""
    tencent_sms_region: str = "ap-guangzhou"
    tencent_sms_template_params: str = '["{code}"]'

    # -------------------- 应用 --------------------
    app_env: str = "development"  # development / staging / production
    dev_sms_code: str = "123456"  # 开发环境固定验证码
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"  # 逗号分隔

    # -------------------- 管理后台 --------------------
    admin_phones: str = ""  # 逗号分隔手机号；验证码登录命中且无 admin 绑定时自动绑定 admin 角色

    @property
    def admin_phone_list(self) -> list[str]:
        """ADMIN_PHONES 逗号分隔解析（空白项忽略）"""
        return [p.strip() for p in self.admin_phones.split(",") if p.strip()]

    @property
    def auth_demo_sms_phone_list(self) -> list[str]:
        return [p.strip() for p in self.auth_demo_sms_allowlist.split(",") if p.strip()]

    @property
    def tencent_sms_template_param_list(self) -> list[str] | None:
        import json

        try:
            params = json.loads(self.tencent_sms_template_params)
        except (TypeError, ValueError):
            return None
        return params if isinstance(params, list) and all(isinstance(param, str) for param in params) else None

    @property
    def cloud_kb_config_map(self) -> dict:
        """CLOUD_KB_CONFIG JSON 解析（非法 JSON 视为空配置）"""
        import json

        try:
            data = json.loads(self.cloud_kb_config or "{}")
            return dict(data) if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def xingchen_flow_id_map(self) -> dict:
        """XINGCHEN_FLOW_IDS JSON 解析（非法 JSON 视为空配置）

        值支持两种形态：
        - str：纯 flow_id（沿用全局 XINGCHEN_API_KEY/SECRET）
        - dict：{"flow_id", "api_key", "api_secret"} 按流凭证覆盖（多应用绑定场景，迭代18）
        """
        import json

        try:
            data = json.loads(self.xingchen_flow_ids or "{}")
            return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @property
    def xingchen_timeout_map(self) -> dict[str, float]:
        """XINGCHEN_TIMEOUTS JSON 解析（非法 JSON 视为空配置）"""
        import json

        try:
            data = json.loads(self.xingchen_timeouts or "{}")
            return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    @property
    def storage_endpoint(self) -> str:
        """对象存储 endpoint 推导：显式 ENDPOINT_URL > scheme/host/port 拼接 > provider+region 默认"""
        if self.storage_endpoint_url:
            return self.storage_endpoint_url
        if self.storage_host:
            port = f":{self.storage_port}" if self.storage_port else ""
            return f"{self.storage_scheme}://{self.storage_host}{port}"
        # 按 provider 推导云厂商默认 endpoint
        if self.storage_provider == "cos" and self.storage_region:
            return f"https://cos.{self.storage_region}.myqcloud.com"
        if self.storage_provider == "oss" and self.storage_region:
            return f"https://s3.oss-{self.storage_region}.aliyuncs.com"
        return ""

    def validate_production(self) -> None:
        """生产环境启动前校验，不安全配置直接拒绝启动"""
        if self.app_env == "production" and self.jwt_secret in (
            "change-me-in-production",
            "change-me-to-a-random-secret-in-production",
            "",
        ):
            raise RuntimeError("生产环境必须配置强随机 JWT_SECRET")
        if self.app_env == "production":
            unsafe = {
                "AUTH_OTP_PEPPER": self.auth_otp_pepper,
                "AUTH_REFRESH_TOKEN_PEPPER": self.auth_refresh_token_pepper,
                "AUTH_INVITE_PEPPER": self.auth_invite_pepper,
            }
            for name, value in unsafe.items():
                if (
                    len(value) < 32
                    or value.startswith("development-only-")
                    or value.startswith("replace-with-")
                ):
                    raise RuntimeError(f"生产环境必须配置强随机 {name}")
            if self.auth_sms_provider not in {"demo", "tencent"}:
                raise RuntimeError("生产环境 AUTH_SMS_PROVIDER 不受支持")
            if self.auth_sms_provider == "demo":
                raise RuntimeError("生产环境禁止使用 demo 短信 provider")
            required_tencent_settings = {
                "TENCENT_SMS_SECRET_ID": self.tencent_sms_secret_id,
                "TENCENT_SMS_SECRET_KEY": self.tencent_sms_secret_key,
                "TENCENT_SMS_SDK_APP_ID": self.tencent_sms_sdk_app_id,
                "TENCENT_SMS_SIGN_NAME": self.tencent_sms_sign_name,
                "TENCENT_SMS_TEMPLATE_ID": self.tencent_sms_template_id,
                "TENCENT_SMS_REGION": self.tencent_sms_region,
            }
            for name, value in required_tencent_settings.items():
                if not value.strip():
                    raise RuntimeError(f"生产环境必须配置 {name}")
            template_params = self.tencent_sms_template_param_list
            if not template_params or not any("{code}" in param for param in template_params):
                raise RuntimeError("生产环境必须配置包含 {code} 的 TENCENT_SMS_TEMPLATE_PARAMS")

    model_config = {"env_file": str(_ENV_FILE), "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
