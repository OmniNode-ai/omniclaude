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

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic import Field, HttpUrl, PrivateAttr
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

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Comprehensive settings for OmniClaude plugins and services."""

    # Private attribute for warning tracking (not serialized, instance-level state)
    _defaults_warned: bool = PrivateAttr(default=False)

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
    # Note: Production values should be configured via .env file, not hardcoded.
    # =========================================================================
    postgres_host: str = Field(
        default="localhost",
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
    # Note: Production values should be configured via .env file, not hardcoded.
    # =========================================================================
    qdrant_host: str = Field(
        default="localhost",
        description="Qdrant host address",
    )
    qdrant_port: int = Field(
        default=6333,
        ge=1,
        le=65535,
        description="Qdrant port",
    )
    qdrant_url: str = Field(
        default="http://localhost:6333",
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
    # -------------------------------------------------------------------------
    # HttpUrl fields use `type: ignore[assignment]` because Pydantic validates
    # and coerces string defaults to HttpUrl at runtime. Mypy sees a type
    # mismatch (str assigned to HttpUrl) but Pydantic handles this correctly
    # via its Field() mechanism. This is a known pattern in pydantic-settings.
    # See: https://docs.pydantic.dev/latest/concepts/types/#urls
    # =========================================================================
    intelligence_service_url: HttpUrl = Field(
        default="http://localhost:8053",  # type: ignore[assignment]  # Pydantic coerces str to HttpUrl at runtime
        description="Intelligence service URL for ONEX pattern discovery and code analysis",
    )
    # DEPRECATED: Use intelligence_service_url instead. This alias is retained
    # for backward compatibility during migration from archon to ONEX naming.
    archon_intelligence_url: HttpUrl | None = Field(
        default=None,
        description="[DEPRECATED] Legacy alias for intelligence_service_url. Use intelligence_service_url instead.",
    )
    main_server_url: HttpUrl = Field(
        default="http://localhost:8181",  # type: ignore[assignment]  # Pydantic coerces str to HttpUrl at runtime
        description="Main server URL",
    )
    semantic_search_url: HttpUrl = Field(
        ...,  # REQUIRED - no default, system fails fast if not in .env
        description="Semantic search service URL for hybrid text/vector search queries. REQUIRED - set SEMANTIC_SEARCH_URL in .env",
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

        # URL-encode special characters in username and password
        # Both may contain URL-unsafe characters like @, :, /, ?, #, etc.
        encoded_user = quote_plus(self.postgres_user)
        if password:
            encoded_password = quote_plus(password)
            return (
                f"{driver}://{encoded_user}:{encoded_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
            )
        return (
            f"{driver}://{encoded_user}"
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
        if not self.postgres_password:
            errors.append("POSTGRES_PASSWORD is not configured")

        # Check Kafka configuration (only if event routing is enabled)
        if self.use_event_routing and not self.get_effective_kafka_bootstrap_servers():
            errors.append(
                "KAFKA_BOOTSTRAP_SERVERS is not configured but USE_EVENT_ROUTING is enabled"
            )

        # Note: Qdrant configuration is not validated here because both qdrant_url
        # and qdrant_host have defaults. Use log_default_warnings() to detect
        # localhost usage that may need production configuration.

        return errors

    def log_default_warnings(self) -> None:
        """Log warnings when using default localhost values.

        This method logs a warning for each service configured with default
        localhost values, which may indicate missing production configuration.
        Warnings are only logged once per instance to avoid log spam.

        Note:
            The warning state is cached per instance via `_defaults_warned`.
            When using the singleton `get_settings()`, warnings will only be
            logged once for the lifetime of the process. For tests that need
            to verify warning behavior, call `reset_warnings()` before each
            test or create a fresh Settings instance.
        """
        if self._defaults_warned:
            return
        self._defaults_warned = True

        if self.postgres_host == "localhost":
            logger.warning(
                "Using default postgres_host='localhost'. Set POSTGRES_HOST in .env for production."
            )

        if not self.kafka_bootstrap_servers:
            logger.warning(
                "Using empty kafka_bootstrap_servers (disabled). "
                "Set KAFKA_BOOTSTRAP_SERVERS in .env for event routing."
            )

        if self.qdrant_host == "localhost":
            logger.warning(
                "Using default qdrant_host='localhost'. Set QDRANT_HOST in .env for production."
            )

    def reset_warnings(self) -> None:
        """Reset the warning state for test isolation.

        This method clears the `_defaults_warned` flag, allowing
        `log_default_warnings()` to emit warnings again. Intended for use
        in test fixtures to ensure warning behavior can be verified across
        multiple tests.

        Example:
            @pytest.fixture
            def settings_with_warnings():
                settings = Settings(...)
                settings.reset_warnings()
                yield settings
        """
        self._defaults_warned = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get singleton settings instance."""
    # Note: Required fields with no defaults (semantic_search_url) are populated
    # from environment variables by Pydantic Settings at runtime - mypy doesn't see this
    instance = Settings()  # type: ignore[call-arg]
    instance.log_default_warnings()
    return instance


settings = get_settings()
