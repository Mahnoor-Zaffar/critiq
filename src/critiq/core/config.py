from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment (see `.env.example`)."""

    model_config = SettingsConfigDict(
        env_prefix="CRITIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "critiq"
    log_level: str = "info"

    # GitHub App
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_webhook_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""

    # LLM (OpenRouter)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model_cheap: str = "openrouter/auto"
    llm_model_strong: str = "openrouter/auto"

    # Infrastructure
    database_url: str = "postgresql+asyncpg://critiq:critiq@localhost:5432/critiq"
    redis_url: str = "redis://localhost:6379/0"

    # Repository intelligence
    repo_index_dir: str = ".critiq-index"

    # Feedback learning loop
    confidence_calibration: bool = True

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
