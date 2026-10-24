"""全局配置：全部可通过环境变量覆盖，便于容器化部署。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """加载项目根目录 .env（KEY=VALUE，# 注释），不覆盖已有环境变量。"""
    p = BASE_DIR / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class Settings:
    app_name: str = "财务管理系统"
    api_prefix: str = "/api/v1"
    debug: bool = _env("APP_DEBUG", "1") == "1"

    # 数据库：复用「实例三」，数据在 schema 文件夹，应用表在 schema app
    db_host: str = _env("PGHOST", "127.0.0.1")
    db_port: int = int(_env("PGPORT", "5432"))
    db_user: str = _env("PGUSER", "postgres")
    db_password: str = _env("PGPASSWORD", "020909")
    db_name: str = _env("PGDATABASE", "实例三")
    data_schema: str = _env("DB_SCHEMA", "文件夹")
    app_schema: str = _env("APP_SCHEMA", "app")
    pool_min: int = int(_env("DB_POOL_MIN", "1"))
    pool_max: int = int(_env("DB_POOL_MAX", "8"))
    statement_timeout_ms: int = int(_env("DB_STMT_TIMEOUT_MS", "15000"))

    # 认证
    jwt_secret: str = _env("JWT_SECRET", "dev-only-secret-change-me-in-production")
    jwt_issuer: str = _env("JWT_ISSUER", "fin-suite")
    token_ttl_minutes: int = int(_env("TOKEN_TTL_MINUTES", "480"))
    refresh_ttl_days: int = int(_env("REFRESH_TTL_DAYS", "7"))

    # 业务默认值
    default_period: str = _env("DEFAULT_PERIOD", "2025-12")
    currency_unit: str = "元"

    # DeepSeek 大模型（api-docs.deepseek.com）：OpenAI 兼容格式
    # 配置方式：项目根目录 .env 文件写 DEEPSEEK_API_KEY=sk-xxx，或设置同名环境变量
    llm_api_key: str = _env("DEEPSEEK_API_KEY", "")
    llm_base_url: str = _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    llm_model: str = _env("DEEPSEEK_MODEL", "deepseek-flash")
    llm_timeout_s: int = int(_env("DEEPSEEK_TIMEOUT_S", "25"))
    # 思考模式与输出上限（官方文档 create-chat-completion）：
    # reasoning_effort 同时控制思考开关与强度——none 关闭思考，low/high/max 开启，默认 high；
    # max_tokens 取值 1~393216，0 表示不传（官方默认：思考 64K / max 强度 128K / 非思考 8K）
    llm_effort: str = _env("DEEPSEEK_REASONING_EFFORT", "high")
    llm_max_tokens: int = int(_env("DEEPSEEK_MAX_TOKENS", "0"))

    web_dir: Path = field(default_factory=lambda: BASE_DIR / "web")
    sql_dir: Path = field(default_factory=lambda: BASE_DIR / "sql")


settings = Settings()
