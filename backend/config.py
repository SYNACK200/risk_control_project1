"""运行配置：仅读取环境变量，不加载 .env。"""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    app_name: str
    api_prefix: str
    log_level: str
    local_access_password: str | None


def load_settings() -> Settings:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise RuntimeError("LOG_LEVEL 必须是有效的日志级别。")

    return Settings(
        app_name=os.getenv("APP_NAME", "银行个人交易流水解析与风险分析 API"),
        api_prefix="/api/v1",
        log_level=log_level,
        local_access_password=os.getenv("LOCAL_ACCESS_PASSWORD") or None,
    )


settings = load_settings()
