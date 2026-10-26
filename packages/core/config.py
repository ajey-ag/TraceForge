from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEFORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://traceforge:traceforge@127.0.0.1:54329/traceforge"
    artifact_root: Path = Path(".artifacts")
    lease_seconds: int = Field(default=30, ge=3, le=3600)
    poll_seconds: float = Field(default=1, ge=0.05, le=60)
    max_attempts: int = Field(default=3, ge=1, le=10)
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if make_url(value).drivername != "postgresql+psycopg":
            raise ValueError("Use a postgresql+psycopg:// database URL")
        return value

    @field_validator("log_level")
    @classmethod
    def valid_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Unsupported logging level")
        return value
