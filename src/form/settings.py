from datetime import timedelta
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_path: Path = Path("data/form.sqlite3")
    images_path: Path = Path("data/images")

    llm_model: str
    llm_api_key: SecretStr
    llm_reasoning_effort: str | None = None
    llm_timeout: int = 120

    max_upload_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    confidence_threshold: int = Field(default=75, ge=0, le=100)
    session_ttl: timedelta = Field(default=timedelta(hours=24), gt=timedelta(0))


def get_settings() -> Settings:
    return Settings()
