from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOOD_",
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )
    app_name: str = "Classroom Mood API"
    database_url: str = "postgresql+psycopg://mood:mood_local_only@127.0.0.1:5432/mood"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://127.0.0.1:5174"]
    ai_service_token: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
