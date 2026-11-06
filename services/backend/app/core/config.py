from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOOD_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    app_name: str = "Classroom Mood API"
    database_url: SecretStr = SecretStr("postgresql+psycopg://mood:mood_local_only@127.0.0.1:5432/mood")
    database_connect_timeout: int = Field(default=2, ge=1, le=60)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout: int = Field(default=10, ge=1, le=60)
    migration_directory: Path = (Path(__file__).resolve().parents[2] / "../../infra/database").resolve()
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://127.0.0.1:5174"]
    user_session_ttl_seconds: int = Field(default=28800, ge=300, le=604800)
    ws_ticket_ttl_seconds: int = Field(default=30, ge=1, le=30)
    realtime_poll_seconds: float = Field(default=1, ge=0.1, le=5, allow_inf_nan=False)
    ai_service_token: SecretStr = SecretStr("")
    ai_control_token: SecretStr = SecretStr("")
    ai_base_url: str = "http://127.0.0.1:8001"
    ai_min_confidence: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)
    allow_simulated_ai: bool = False

    @field_validator("database_url")
    @classmethod
    def postgres_database(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+psycopg" or not url.database:
                raise ValueError
        except Exception:
            raise ValueError("数据库必须使用 postgresql+psycopg 并指定库名") from None
        return value

    @field_validator("ai_base_url")
    @classmethod
    def ai_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("AI 服务地址必须为不含凭据、查询或片段的 HTTP 地址")
        return value.rstrip("/")

    @model_validator(mode="after")
    def isolated_tokens(self):
        service = self.ai_service_token.get_secret_value()
        control = self.ai_control_token.get_secret_value()
        if service and control and service == control:
            raise ValueError("AI 入库令牌和 AI 控制令牌必须独立")
        if service.startswith("usr_") or control.startswith("usr_"):
            raise ValueError("AI 服务令牌不能使用用户令牌保留前缀 usr_")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
