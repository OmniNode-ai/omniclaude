"""Minimal OmniClaude settings for plugin infrastructure."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_and_load_env() -> None:
    """Load .env file from project root."""
    from dotenv import load_dotenv

    current = Path(__file__).resolve().parent
    for _ in range(10):
        env_file = current / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)
            return
        parent = current.parent
        if parent == current:
            break
        current = parent


_find_and_load_env()


class Settings(BaseSettings):
    """Minimal settings for OmniClaude plugins."""

    kafka_bootstrap_servers: str = Field(
        default="",
        description="Kafka broker addresses (e.g., 192.168.86.200:29092)",
    )
    kafka_intelligence_bootstrap_servers: str | None = Field(
        default=None,
        description="Legacy alias for kafka_bootstrap_servers",
    )
    request_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Request timeout in milliseconds",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def get_effective_kafka_bootstrap_servers(self) -> str:
        """Get Kafka servers with legacy alias fallback."""
        return (
            self.kafka_bootstrap_servers
            or self.kafka_intelligence_bootstrap_servers
            or ""
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get singleton settings instance."""
    return Settings()


settings = get_settings()
