"""OmniClaude settings for plugin infrastructure.

Provides comprehensive configuration for all OmniClaude services including:
- Kafka/Redpanda event bus
- PostgreSQL database
- Qdrant vector database
- Valkey cache
- Service URLs
- Feature flags
- Quality enforcement phases
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, HttpUrl
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
    """Comprehensive settings for OmniClaude plugins and services."""

    # =========================================================================
    # KAFKA / REDPANDA CONFIGURATION
    # =========================================================================
    kafka_bootstrap_servers: str = Field(
        default="",
        description="Kafka broker addresses (e.g., 192.168.86.200:29092)",
    )
    kafka_intelligence_bootstrap_servers: str | None = Field(
        default=None,
        description="Legacy alias for kafka_bootstrap_servers",
    )
    kafka_environment: str = Field(
        default="dev",
        description="Kafka topic environment prefix (dev, staging, prod)",
    )
    kafka_group_id: str = Field(
        default="omniclaude-hooks",
        description="Kafka consumer group ID",
    )
    request_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Kafka request timeout in milliseconds",
    )

    # =========================================================================
    # POSTGRESQL DATABASE CONFIGURATION
    # =========================================================================
    postgres_host: str = Field(
        default="192.168.86.200",
        description="PostgreSQL host address",
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
        description="PostgreSQL username",
    )
    postgres_password: str = Field(
        default="",
        description="PostgreSQL password (loaded from environment)",
    )

    # =========================================================================
    # QDRANT VECTOR DATABASE CONFIGURATION
    # =========================================================================
    qdrant_host: str = Field(
        default="192.168.86.101",
        description="Qdrant host address",
    )
    qdrant_port: int = Field(
        default=6333,
        ge=1,
        le=65535,
        description="Qdrant port",
    )
    qdrant_url: str = Field(
        default="http://192.168.86.101:6333",
        description="Full Qdrant URL",
    )

    # =========================================================================
    # VALKEY CACHE CONFIGURATION
    # =========================================================================
    valkey_url: str | None = Field(
        default=None,
        description="Valkey/Redis connection URL (e.g., redis://:password@host:6379/0)",
    )
    enable_intelligence_cache: bool = Field(
        default=True,
        description="Enable Valkey caching for intelligence queries",
    )

    # Cache TTL settings (seconds)
    cache_ttl_patterns: int = Field(
        default=300,
        ge=0,
        description="TTL for pattern cache entries (seconds)",
    )
    cache_ttl_infrastructure: int = Field(
        default=3600,
        ge=0,
        description="TTL for infrastructure cache entries (seconds)",
    )
    cache_ttl_schemas: int = Field(
        default=1800,
        ge=0,
        description="TTL for schema cache entries (seconds)",
    )

    # =========================================================================
    # SERVICE URLS CONFIGURATION
    # =========================================================================
    archon_intelligence_url: HttpUrl = Field(
        default="http://localhost:8053",  # type: ignore[assignment]
        description="Archon Intelligence service URL",
    )
    intelligence_service_url: HttpUrl | None = Field(
        default=None,
        description="Legacy alias for archon_intelligence_url",
    )
    main_server_url: HttpUrl = Field(
        default="http://localhost:8181",  # type: ignore[assignment]
        description="Main server URL",
    )

    # =========================================================================
    # FEATURE FLAGS
    # =========================================================================
    use_event_routing: bool = Field(
        default=True,
        description="Enable event-based agent routing",
    )
    enable_pattern_quality_filter: bool = Field(
        default=False,
        description="Enable pattern quality filtering",
    )
    min_pattern_quality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum pattern quality threshold (0.0-1.0)",
    )

    # =========================================================================
    # QUALITY ENFORCEMENT PHASES
    # =========================================================================
    enable_phase_1_validation: bool = Field(
        default=True,
        description="Enable Phase 1: Fast Validation (<100ms)",
    )
    enable_phase_2_rag: bool = Field(
        default=True,
        description="Enable Phase 2: RAG Intelligence (<500ms)",
    )
    enable_phase_3_correction: bool = Field(
        default=True,
        description="Enable Phase 3: Correction Generation",
    )
    enable_phase_4_ai_quorum: bool = Field(
        default=False,
        description="Enable Phase 4: AI Quorum Scoring (<1000ms)",
    )
    performance_budget_seconds: float = Field(
        default=2.0,
        ge=0.0,
        description="Total performance budget for quality enforcement (seconds)",
    )
    enforcement_mode: Literal["advisory", "blocking", "auto-fix"] = Field(
        default="advisory",
        description="Enforcement mode: advisory (warn), blocking (reject), auto-fix (correct)",
    )

    # =========================================================================
    # AGENT CONFIGURATION
    # =========================================================================
    registry_path: str | None = Field(
        default=None,
        description="Path to agent registry directory",
    )
    health_check_port: int = Field(
        default=8070,
        ge=1,
        le=65535,
        description="Health check server port",
    )

    # =========================================================================
    # PYDANTIC SETTINGS CONFIG
    # =========================================================================
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    def get_effective_kafka_bootstrap_servers(self) -> str:
        """Get Kafka servers with legacy alias fallback."""
        return self.kafka_bootstrap_servers or self.kafka_intelligence_bootstrap_servers or ""

    def get_effective_postgres_password(self) -> str:
        """Get PostgreSQL password.

        Returns the configured password. This method exists for consistency
        with patterns that may need to transform or validate the password.
        """
        return self.postgres_password

    def get_postgres_dsn(self, async_driver: bool = False) -> str:
        """Build PostgreSQL connection string.

        Args:
            async_driver: If True, use asyncpg driver prefix; otherwise psycopg2.

        Returns:
            Full PostgreSQL DSN connection string.
        """
        driver = "postgresql+asyncpg" if async_driver else "postgresql"
        password = self.get_effective_postgres_password()

        # URL-encode special characters in password if present
        if password:
            # Properly encode all URL-unsafe characters
            encoded_password = quote_plus(password)
            return (
                f"{driver}://{self.postgres_user}:{encoded_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
            )
        return (
            f"{driver}://{self.postgres_user}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    def validate_required_services(self) -> list[str]:
        """Validate that required services are configured.

        Returns:
            List of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        # Check PostgreSQL configuration
        if not self.postgres_host:
            errors.append("POSTGRES_HOST is not configured")
        if not self.postgres_database:
            errors.append("POSTGRES_DATABASE is not configured")
        if not self.postgres_user:
            errors.append("POSTGRES_USER is not configured")

        # Check Kafka configuration (only if event routing is enabled)
        if self.use_event_routing and not self.get_effective_kafka_bootstrap_servers():
            errors.append(
                "KAFKA_BOOTSTRAP_SERVERS is not configured but USE_EVENT_ROUTING is enabled"
            )

        # Check Qdrant configuration
        if not self.qdrant_url and not self.qdrant_host:
            errors.append("Neither QDRANT_URL nor QDRANT_HOST is configured")

        return errors


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get singleton settings instance."""
    return Settings()


settings = get_settings()
