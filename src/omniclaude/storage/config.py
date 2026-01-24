"""Configuration for session snapshot storage.

Loads from environment variables with OMNICLAUDE_STORAGE_ prefix.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigSessionStorage(BaseSettings):
    """Configuration for session snapshot PostgreSQL storage.

    Environment variables use the OMNICLAUDE_STORAGE_ prefix.
    Example: OMNICLAUDE_STORAGE_POSTGRES_HOST=192.168.86.200
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_STORAGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # PostgreSQL connection
    postgres_host: str = Field(
        default="192.168.86.200",
        description="PostgreSQL host",
    )
    postgres_port: int = Field(
        default=5436,
        ge=1,
        le=65535,
        description="PostgreSQL port",
    )
    postgres_database: str = Field(
        default="omninode_bridge",
        description="PostgreSQL database name",
    )
    postgres_user: str = Field(
        default="postgres",
        description="PostgreSQL user",
    )
    postgres_password: SecretStr = Field(
        ...,  # Required
        description="PostgreSQL password - set via OMNICLAUDE_STORAGE_POSTGRES_PASSWORD env var",
    )

    # Connection pool
    pool_min_size: int = Field(
        default=2,
        ge=1,
        le=100,
        description="Minimum connection pool size",
    )
    pool_max_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum connection pool size",
    )

    # Query timeouts
    query_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Query timeout in seconds",
    )

    @property
    def dsn(self) -> str:
        """Build PostgreSQL DSN from components.

        Returns:
            PostgreSQL connection string.
        """
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_database}"
        )

    @property
    def dsn_async(self) -> str:
        """Build async PostgreSQL DSN for asyncpg.

        Returns:
            PostgreSQL connection string with postgresql+asyncpg scheme.
        """
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_database}"
        )

    @property
    def dsn_safe(self) -> str:
        """Build PostgreSQL DSN with password masked (safe for logging).

        Returns:
            PostgreSQL connection string with password replaced by ***.
        """
        return (
            f"postgresql://{self.postgres_user}:***"
            f"@{self.postgres_host}:{self.postgres_port}"
            f"/{self.postgres_database}"
        )

    def __repr__(self) -> str:
        """Safe string representation that doesn't expose credentials.

        Returns:
            String representation with masked password.
        """
        return f"ConfigSessionStorage(dsn={self.dsn_safe!r})"
