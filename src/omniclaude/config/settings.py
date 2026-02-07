"""OmniClaude settings for plugin infrastructure.

Provides comprehensive configuration for all OmniClaude services including:
- Kafka/Redpanda event bus
- PostgreSQL database
- Qdrant vector database
- Valkey cache
- Service URLs
- Feature flags
- Quality enforcement phases

IMPORTANT: Required Configuration
---------------------------------
This module follows FAIL-FAST principles. Required services must be explicitly
configured via environment variables or .env file. There are NO hardcoded
localhost defaults that could mask missing configuration.

Required environment variables when services are enabled:

    # Kafka (required when USE_EVENT_ROUTING=true)
    KAFKA_BOOTSTRAP_SERVERS=localhost:9092
    KAFKA_ENVIRONMENT=dev  # or staging, prod - MUST be explicit

    # PostgreSQL (required when ENABLE_POSTGRES=true)
    POSTGRES_HOST=localhost
    POSTGRES_PORT=5432
    POSTGRES_DATABASE=mydb
    POSTGRES_USER=postgres
    POSTGRES_PASSWORD=your_password

    # Qdrant (required when ENABLE_QDRANT=true)
    QDRANT_HOST=localhost
    QDRANT_PORT=6333
    QDRANT_URL=http://localhost:6333

    # Service URLs (optional, but recommended for production)
    INTELLIGENCE_SERVICE_URL=http://localhost:8053
    MAIN_SERVER_URL=http://localhost:8181
    SEMANTIC_SEARCH_URL=http://localhost:8055

To disable a service entirely, set its enable flag to false:
    ENABLE_POSTGRES=false
    ENABLE_QDRANT=false
    USE_EVENT_ROUTING=false
"""

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote

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
        description="Kafka broker addresses (e.g., localhost:9092)",
    )
    kafka_intelligence_bootstrap_servers: str | None = Field(
        default=None,
        description="Legacy alias for kafka_bootstrap_servers",
    )
    kafka_environment: str = Field(
        default="",
        description=(
            "Kafka topic environment prefix (dev, staging, prod). "
            "REQUIRED when USE_EVENT_ROUTING=true. No default to prevent "
            "accidental cross-environment event routing."
        ),
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
    # -------------------------------------------------------------------------
    # FAIL-FAST: All fields default to empty. When ENABLE_POSTGRES=true,
    # validate_required_services() will catch missing configuration.
    # This prevents silent localhost connections in production.
    # =========================================================================
    postgres_host: str = Field(
        default="",
        description=(
            "PostgreSQL host address. REQUIRED when ENABLE_POSTGRES=true. "
            "No default to prevent silent localhost connections."
        ),
    )
    postgres_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description=(
            "PostgreSQL port. REQUIRED when ENABLE_POSTGRES=true. "
            "Standard port is 5432. Set to 0 to indicate unconfigured."
        ),
    )
    postgres_database: str = Field(
        default="",
        description=(
            "PostgreSQL database name. REQUIRED when ENABLE_POSTGRES=true. "
            "No default to prevent connecting to wrong database."
        ),
    )
    postgres_user: str = Field(
        default="",
        description=(
            "PostgreSQL username. REQUIRED when ENABLE_POSTGRES=true. "
            "No default to prevent unauthorized access attempts."
        ),
    )
    postgres_password: str = Field(  # nosec: Pydantic field, reads from env
        default="",
        description="PostgreSQL password. REQUIRED when ENABLE_POSTGRES=true.",
    )
    enable_postgres: bool = Field(
        default=False,
        description=(
            "Enable PostgreSQL database connection. When True, all POSTGRES_* "
            "fields must be configured. Defaults to False for safety."
        ),
    )

    # =========================================================================
    # QDRANT VECTOR DATABASE CONFIGURATION
    # -------------------------------------------------------------------------
    # FAIL-FAST: All fields default to empty/zero. When ENABLE_QDRANT=true,
    # validate_required_services() will catch missing configuration.
    # This prevents silent localhost connections in production.
    # =========================================================================
    qdrant_host: str = Field(
        default="",
        description=(
            "Qdrant host address. REQUIRED when ENABLE_QDRANT=true. "
            "No default to prevent silent localhost connections."
        ),
    )
    qdrant_port: int = Field(
        default=0,
        ge=0,
        le=65535,
        description=(
            "Qdrant port. REQUIRED when ENABLE_QDRANT=true. "
            "Standard port is 6333. Set to 0 to indicate unconfigured."
        ),
    )
    qdrant_url: str = Field(
        default="",
        description=(
            "Full Qdrant URL. REQUIRED when ENABLE_QDRANT=true. "
            "No default to prevent silent localhost connections."
        ),
    )
    enable_qdrant: bool = Field(
        default=False,
        description=(
            "Enable Qdrant vector database. When True, QDRANT_HOST/QDRANT_URL "
            "must be configured. Defaults to False for safety."
        ),
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
    # These service URLs are OPTIONAL. When not configured, features that depend
    # on them will be gracefully disabled. No localhost defaults to prevent
    # silent connection attempts to non-existent local services.
    #
    # HttpUrl | None pattern allows empty/None values while still validating
    # any provided URLs.
    # =========================================================================
    intelligence_service_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Intelligence service URL for ONEX pattern discovery and code analysis. "
            "Optional - when not set, intelligence features are disabled."
        ),
    )
    # DEPRECATED: Use intelligence_service_url instead. This alias is retained
    # for backward compatibility during migration from archon to ONEX naming.
    archon_intelligence_url: HttpUrl | None = Field(
        default=None,
        description="[DEPRECATED] Legacy alias for intelligence_service_url. Use intelligence_service_url instead.",
    )
    main_server_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Main server URL. Optional - when not set, main server features are disabled."
        ),
    )
    semantic_search_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Semantic search service URL for hybrid text/vector search queries. "
            "Optional - when not set, semantic search features are disabled."
        ),
    )

    # =========================================================================
    # FEATURE FLAGS
    # =========================================================================
    use_event_routing: bool = Field(
        default=False,
        description=(
            "Enable event-based agent routing via Kafka. When True, "
            "KAFKA_BOOTSTRAP_SERVERS and KAFKA_ENVIRONMENT must be configured. "
            "Defaults to False for safety."
        ),
    )
    use_onex_routing_nodes: bool = Field(
        default=False,
        description=(
            "Enable ONEX routing nodes for agent routing. When True, "
            "route_via_events_wrapper calls HandlerRoutingDefault (compute) "
            "and HandlerRoutingEmitter (effect) instead of direct AgentRouter. "
            "Defaults to False for safety."
        ),
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
    enable_disabled_pattern_filter: bool = Field(
        default=True,
        description=(
            "Enable runtime kill switch for patterns. When True, ManifestInjector "
            "checks disabled_patterns_current materialized view before injection. "
            "Requires ENABLE_POSTGRES=true; effectively a no-op when Postgres is disabled."
        ),
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
        return (
            self.kafka_bootstrap_servers
            or self.kafka_intelligence_bootstrap_servers
            or ""
        )

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
        password = self.get_effective_postgres_password()  # nosec

        # URL-encode special characters in username and password.
        # Both may contain URL-unsafe characters like @, :, /, ?, #, %, etc.
        # Using quote() with safe='' ensures ALL special characters are encoded,
        # including spaces as %20 (more compatible than quote_plus's + encoding).
        encoded_user = quote(self.postgres_user, safe="")
        if password:
            encoded_password = quote(password, safe="")  # nosec
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

        This method implements FAIL-FAST validation. When a service is enabled,
        ALL required configuration must be explicitly provided. There are no
        fallback defaults that could mask missing configuration.

        Returns:
            List of validation error messages. Empty list means valid.

        Example:
            >>> settings = Settings(enable_postgres=True)
            >>> errors = settings.validate_required_services()
            >>> if errors:
            ...     raise ValueError(f"Missing configuration: {errors}")
        """
        errors: list[str] = []

        # =====================================================================
        # KAFKA VALIDATION
        # When event routing is enabled, both bootstrap servers AND environment
        # must be explicitly configured. No defaults to prevent cross-env routing.
        # =====================================================================
        if self.use_event_routing:
            if not self.get_effective_kafka_bootstrap_servers():
                errors.append(
                    "KAFKA_BOOTSTRAP_SERVERS is required when USE_EVENT_ROUTING=true. "
                    "Set KAFKA_BOOTSTRAP_SERVERS in .env or set USE_EVENT_ROUTING=false."
                )
            if not self.kafka_environment:
                errors.append(
                    "KAFKA_ENVIRONMENT is required when USE_EVENT_ROUTING=true. "
                    "Must be explicitly set to 'dev', 'staging', or 'prod' to prevent "
                    "accidental cross-environment event routing."
                )

        # =====================================================================
        # POSTGRESQL VALIDATION
        # When enabled, ALL connection parameters must be explicitly configured.
        # No localhost defaults to prevent silent local connections in production.
        # =====================================================================
        if self.enable_postgres:
            if not self.postgres_host:
                errors.append(
                    "POSTGRES_HOST is required when ENABLE_POSTGRES=true. "
                    "Set POSTGRES_HOST in .env or set ENABLE_POSTGRES=false."
                )
            if self.postgres_port == 0:
                errors.append(
                    "POSTGRES_PORT is required when ENABLE_POSTGRES=true. "
                    "Standard port is 5432. Set POSTGRES_PORT in .env or set ENABLE_POSTGRES=false."
                )
            if not self.postgres_database:
                errors.append(
                    "POSTGRES_DATABASE is required when ENABLE_POSTGRES=true. "
                    "Set POSTGRES_DATABASE in .env or set ENABLE_POSTGRES=false."
                )
            if not self.postgres_user:
                errors.append(
                    "POSTGRES_USER is required when ENABLE_POSTGRES=true. "
                    "Set POSTGRES_USER in .env or set ENABLE_POSTGRES=false."
                )
            if not self.postgres_password:
                errors.append(
                    "POSTGRES_PASSWORD is required when ENABLE_POSTGRES=true. "
                    "Set POSTGRES_PASSWORD in .env or set ENABLE_POSTGRES=false."
                )

        # =====================================================================
        # QDRANT VALIDATION
        # When enabled, connection parameters must be explicitly configured.
        # Either qdrant_url OR (qdrant_host + qdrant_port) must be set.
        # =====================================================================
        if self.enable_qdrant:
            has_url = bool(self.qdrant_url)
            has_host_port = bool(self.qdrant_host) and self.qdrant_port != 0

            if not has_url and not has_host_port:
                errors.append(
                    "QDRANT_URL or (QDRANT_HOST + QDRANT_PORT) is required when ENABLE_QDRANT=true. "
                    "Set QDRANT_URL in .env (e.g., http://localhost:6333) or set ENABLE_QDRANT=false."
                )

        return errors

    def log_default_warnings(self) -> None:
        """Log informational messages about disabled services.

        This method logs INFO messages for services that are disabled by default.
        These are not warnings since the defaults are intentionally safe (disabled).
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

        # Log disabled services as INFO (not warnings, since disabled is safe)
        if not self.enable_postgres:
            logger.info(
                "PostgreSQL is disabled (ENABLE_POSTGRES=false). "
                "Set ENABLE_POSTGRES=true and configure POSTGRES_* variables to enable."
            )

        if not self.use_event_routing:
            logger.info(
                "Kafka event routing is disabled (USE_EVENT_ROUTING=false). "
                "Set USE_EVENT_ROUTING=true and configure KAFKA_* variables to enable."
            )

        if not self.enable_qdrant:
            logger.info(
                "Qdrant vector database is disabled (ENABLE_QDRANT=false). "
                "Set ENABLE_QDRANT=true and configure QDRANT_* variables to enable."
            )

        # Warn about optional services that enhance functionality
        if not self.intelligence_service_url:
            logger.info(
                "Intelligence service URL not configured. "
                "Set INTELLIGENCE_SERVICE_URL to enable pattern discovery features."
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
    """Get singleton settings instance.

    Returns a cached Settings instance. The singleton pattern ensures
    consistent configuration across the application. The instance is
    created lazily on first call and reused thereafter.

    Note:
        For test isolation, use `clear_settings_cache()` to reset the
        singleton before each test that needs fresh settings.
    """
    instance = Settings()
    instance.log_default_warnings()
    return instance


def clear_settings_cache() -> None:
    """Clear the settings singleton cache for test isolation.

    This function clears the lru_cache on `get_settings()`, ensuring
    the next call creates a fresh Settings instance. Use this in test
    fixtures to guarantee test isolation.

    Example:
        @pytest.fixture(autouse=True)
        def reset_settings():
            clear_settings_cache()
            yield
            clear_settings_cache()

        def test_warning_behavior():
            # Fresh settings instance, warnings will fire
            settings = get_settings()
            assert settings._defaults_warned is True

        def test_another_warning_scenario():
            # Also gets fresh settings due to fixture
            settings = get_settings()
            # ...
    """
    get_settings.cache_clear()


settings = get_settings()
