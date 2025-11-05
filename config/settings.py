"""
OmniClaude Pydantic Settings Configuration Framework.

This module provides type-safe configuration management using Pydantic Settings.
All configuration is loaded from environment variables with validation and type conversion.

Architecture:
    - Single Settings class organized into logical sections
    - Type hints and validators for all configuration
    - Support for multiple environment files (.env, .env.dev, .env.test, .env.prod)
    - Validation on startup with clear error messages
    - Sensitive values (passwords, API keys) handled securely

Environment File Priority:
    1. .env.{ENVIRONMENT} (e.g., .env.dev, .env.prod)
    2. .env (default/fallback)
    3. System environment variables (highest priority)

Usage:
    from config import settings

    # Access configuration values with type safety
    kafka_servers = settings.kafka_bootstrap_servers
    db_host = settings.postgres_host
    api_key = settings.gemini_api_key

Requirements:
    pip install pydantic pydantic-settings

See Also:
    - .env.example: Template with all configuration variables
    - config/README.md: Detailed usage documentation
    - SECURITY_KEY_ROTATION.md: API key management guide

Implementation:
    Phase 2 - ADR-001 Type-Safe Configuration Framework
"""

import logging
from pathlib import Path
from typing import Optional

from pydantic import Field, HttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Centralized configuration for OmniClaude services.

    All configuration is loaded from environment variables with type validation.
    Organized into logical sections matching .env.example structure.

    Sections:
        1. External Service Discovery (omniarchon services)
        2. Shared Infrastructure (Kafka, PostgreSQL)
        3. AI Provider API Keys
        4. Local Services (Qdrant, Valkey)
        5. Feature Flags & Optimization
        6. Optional Configuration

    Attributes are organized by section with comprehensive documentation.
    """

    # =========================================================================
    # EXTERNAL SERVICE DISCOVERY (from omniarchon)
    # =========================================================================
    # Services provided by omniarchon repository (192.168.86.101)

    archon_intelligence_url: HttpUrl = Field(
        default="http://192.168.86.101:8053",
        description="Archon Intelligence API - Code quality, pattern discovery, RAG queries",
    )

    archon_search_url: HttpUrl = Field(
        default="http://192.168.86.101:8055",
        description="Archon Search API - Vector search, semantic search",
    )

    archon_bridge_url: HttpUrl = Field(
        default="http://192.168.86.101:8054",
        description="Archon Bridge API - Bridge services between systems",
    )

    archon_mcp_url: HttpUrl = Field(
        default="http://192.168.86.101:8051",
        description="Archon MCP Server - Model Context Protocol server",
    )

    intelligence_service_url: Optional[HttpUrl] = Field(
        default=None,
        description="Legacy alias for intelligence service (backward compatibility)",
    )

    main_server_url: HttpUrl = Field(
        default="http://192.168.86.101:8181",
        description="Archon Main Server (if different from intelligence)",
    )

    # =========================================================================
    # SHARED INFRASTRUCTURE - KAFKA/REDPANDA (from omninode_bridge)
    # =========================================================================
    # Central message broker for distributed intelligence and observability
    # Running on 192.168.86.200

    kafka_bootstrap_servers: str = Field(
        default="192.168.86.200:29092",
        description=(
            "Kafka broker addresses. "
            "Use omninode-bridge-redpanda:9092 for Docker services, "
            "192.168.86.200:29092 for host scripts"
        ),
    )

    kafka_intelligence_bootstrap_servers: Optional[str] = Field(
        default=None,
        description="Legacy alias for Kafka bootstrap servers (backward compatibility)",
    )

    kafka_enable_intelligence: bool = Field(
        default=True, description="Enable event-based intelligence queries"
    )

    kafka_enable_logging: bool = Field(
        default=True, description="Enable Kafka event logging"
    )

    enable_event_based_discovery: bool = Field(
        default=True, description="Enable event-first pattern discovery"
    )

    enable_filesystem_fallback: bool = Field(
        default=True, description="Fallback to filesystem on event failure"
    )

    prefer_event_patterns: bool = Field(
        default=True, description="Prefer event patterns over built-in patterns"
    )

    kafka_request_timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=60000,
        description="Request timeout in milliseconds (1-60 seconds)",
    )

    kafka_doc_topic: str = Field(
        default="documentation-changed",
        description="Documentation change tracking topic",
    )

    # =========================================================================
    # SHARED INFRASTRUCTURE - POSTGRESQL (from omninode_bridge)
    # =========================================================================
    # Shared database for agent tracking, pattern storage, observability
    # Database: omninode_bridge (34+ tables)

    postgres_host: str = Field(
        default="192.168.86.200",
        description="PostgreSQL server host (use omninode-bridge-postgres for Docker)",
    )

    postgres_port: int = Field(
        default=5436,
        ge=1,
        le=65535,
        description="PostgreSQL server port (5432 internal, 5436 external)",
    )

    postgres_database: str = Field(
        default="omninode_bridge", description="PostgreSQL database name"
    )

    postgres_user: str = Field(default="postgres", description="PostgreSQL username")

    postgres_password: str = Field(
        default="", description="PostgreSQL password (REQUIRED - set in .env)"
    )

    # Legacy aliases for backward compatibility
    postgres_db: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_database"
    )

    db_password: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_password"
    )

    omninode_bridge_postgres_password: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_password"
    )

    # PostgreSQL Connection Pool Configuration
    postgres_pool_min_size: int = Field(
        default=2, ge=1, le=100, description="Minimum connection pool size"
    )

    postgres_pool_max_size: int = Field(
        default=10, ge=1, le=100, description="Maximum connection pool size"
    )

    # =========================================================================
    # AI PROVIDER API KEYS
    # =========================================================================
    # Sensitive credentials - never commit to version control

    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Google Gemini API key (get from: https://console.cloud.google.com/apis/credentials)",
    )

    google_api_key: Optional[str] = Field(
        default=None,
        description="Google API Key for Pydantic AI compatibility (usually same as gemini_api_key)",
    )

    zai_api_key: Optional[str] = Field(
        default=None,
        description="Z.ai API key for GLM models (get from: https://z.ai/dashboard)",
    )

    openai_api_key: Optional[str] = Field(
        default=None, description="OpenAI API key (optional)"
    )

    # =========================================================================
    # LOCAL SERVICES CONFIGURATION
    # =========================================================================
    # Services running locally on development machine

    # Qdrant Vector Database
    qdrant_host: str = Field(default="localhost", description="Qdrant server host")

    qdrant_port: int = Field(
        default=6333, ge=1, le=65535, description="Qdrant server port"
    )

    qdrant_url: HttpUrl = Field(
        default="http://localhost:6333",
        description="Qdrant full URL (derived from host:port)",
    )

    # Valkey Caching (Redis-compatible)
    enable_intelligence_cache: bool = Field(
        default=True, description="Enable distributed caching for intelligence queries"
    )

    valkey_url: Optional[str] = Field(
        default=None,
        description=(
            "Valkey connection URL (Redis protocol). "
            "Format: redis://:password@host:port/db "
            "Example: redis://:mypassword@archon-valkey:6379/0"
        ),
    )

    # Cache TTLs (seconds)
    cache_ttl_patterns: int = Field(
        default=300,
        ge=0,
        description="Cache TTL for pattern discovery (seconds, 0=no cache)",
    )

    cache_ttl_infrastructure: int = Field(
        default=3600,
        ge=0,
        description="Cache TTL for infrastructure topology (seconds)",
    )

    cache_ttl_schemas: int = Field(
        default=1800, ge=0, description="Cache TTL for database schemas (seconds)"
    )

    # =========================================================================
    # FEATURE FLAGS & OPTIMIZATION
    # =========================================================================

    # Manifest Cache Configuration
    manifest_cache_ttl_seconds: int = Field(
        default=300, ge=0, description="Base cache TTL for manifest injection (seconds)"
    )

    # Pattern Quality Filtering (Phase 2)
    enable_pattern_quality_filter: bool = Field(
        default=False, description="Enable quality filtering for pattern injection"
    )

    min_pattern_quality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum pattern quality threshold (0.0-1.0). "
            "0.9+=Excellent, 0.7-0.9=Good, 0.5-0.7=Fair, <0.5=Poor (filtered)"
        ),
    )

    # =========================================================================
    # OPTIONAL CONFIGURATION
    # =========================================================================

    # Development Repository Paths
    omniarchon_path: Optional[str] = Field(
        default=None,
        description="Path to omniarchon repository (auto-resolved if not set)",
    )

    omninode_bridge_path: Optional[str] = Field(
        default=None,
        description="Path to omninode_bridge repository (auto-resolved if not set)",
    )

    # Git Hooks Configuration
    git_hook_validate_docs: bool = Field(
        default=False, description="Enable documentation validation before git push"
    )

    # Agent Router Configuration
    agent_registry_path: Optional[str] = Field(
        default=None,
        description="Path to agent registry YAML (defaults to ~/.claude/agent-definitions/agent-registry.yaml)",
    )

    agent_definitions_path: Optional[str] = Field(
        default=None,
        description="Path to agent definitions directory (defaults to ~/.claude/agent-definitions/)",
    )

    # Routing Service Configuration
    routing_adapter_port: int = Field(
        default=8055, ge=1, le=65535, description="Routing adapter service HTTP port"
    )

    routing_adapter_host: str = Field(
        default="0.0.0.0",  # noqa: S104  # Service needs to bind to all interfaces for Docker
        description="Routing adapter service bind address",
    )

    routing_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Routing operation timeout (milliseconds)",
    )

    request_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="General request timeout (milliseconds)",
    )

    max_batch_size: int = Field(
        default=100, ge=1, le=1000, description="Maximum routing requests per batch"
    )

    cache_ttl_seconds: int = Field(
        default=3600, ge=0, description="General cache TTL (seconds)"
    )

    health_check_interval: int = Field(
        default=30, ge=1, le=3600, description="Health check interval (seconds)"
    )

    # Environment detection
    environment: str = Field(
        default="development",
        description="Runtime environment (development, test, production)",
    )

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @field_validator("postgres_port", "qdrant_port", "routing_adapter_port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Validate port is in valid range (1-65535)."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("min_pattern_quality")
    @classmethod
    def validate_quality_threshold(cls, v: float) -> float:
        """Validate pattern quality threshold is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"Pattern quality threshold must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("postgres_pool_min_size", "postgres_pool_max_size")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        """Validate connection pool size is reasonable."""
        if v < 1:
            raise ValueError(f"Pool size must be at least 1, got {v}")
        if v > 100:
            logger.warning(
                f"Pool size {v} is very large, consider reducing for resource efficiency"
            )
        return v

    @field_validator(
        "kafka_request_timeout_ms", "routing_timeout_ms", "request_timeout_ms"
    )
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout is reasonable (1-60 seconds)."""
        if not 1000 <= v <= 60000:
            raise ValueError(f"Timeout must be between 1000ms and 60000ms, got {v}")
        return v

    @field_validator("agent_registry_path", mode="before")
    @classmethod
    def resolve_agent_registry_path(cls, v: Optional[str]) -> str:
        """Resolve agent registry path with default."""
        if v:
            return v
        home_dir = Path.home()
        return str(home_dir / ".claude" / "agent-definitions" / "agent-registry.yaml")

    @field_validator("agent_definitions_path", mode="before")
    @classmethod
    def resolve_agent_definitions_path(cls, v: Optional[str]) -> str:
        """Resolve agent definitions directory with default."""
        if v:
            return v
        home_dir = Path.home()
        return str(home_dir / ".claude" / "agent-definitions")

    # =========================================================================
    # PYDANTIC SETTINGS CONFIGURATION
    # =========================================================================

    model_config = SettingsConfigDict(
        # Environment file configuration
        env_file=".env",
        env_file_encoding="utf-8",
        # Support for multiple environment files
        # Priority: .env.{environment} > .env > system env vars
        env_prefix="",
        # Case insensitive environment variable matching
        case_sensitive=False,
        # Ignore extra environment variables not defined in model
        extra="ignore",
        # Allow arbitrary types (for HttpUrl, etc.)
        arbitrary_types_allowed=True,
        # Validate on assignment (catch errors early)
        validate_assignment=True,
        # Use enum values instead of enum instances
        use_enum_values=True,
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_postgres_dsn(self, async_driver: bool = False) -> str:
        """
        Get PostgreSQL connection string (DSN).

        Args:
            async_driver: If True, use asyncpg:// scheme, else postgresql://

        Returns:
            PostgreSQL connection string

        Example:
            >>> settings.get_postgres_dsn()
            'postgresql://postgres:password@192.168.86.200:5436/omninode_bridge'
            >>> settings.get_postgres_dsn(async_driver=True)
            'postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge'
        """
        scheme = "postgresql+asyncpg" if async_driver else "postgresql"
        return (
            f"{scheme}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    def get_effective_postgres_password(self) -> str:
        """
        Get effective PostgreSQL password (handles legacy aliases).

        Returns:
            PostgreSQL password from primary field or legacy aliases

        Raises:
            ValueError: If no password is set
        """
        password = (
            self.postgres_password
            or self.db_password
            or self.omninode_bridge_postgres_password
        )
        if not password:
            raise ValueError(
                "PostgreSQL password not configured. "
                "Set POSTGRES_PASSWORD in .env file"
            )
        return password

    def get_effective_kafka_bootstrap_servers(self) -> str:
        """
        Get effective Kafka bootstrap servers (handles legacy aliases).

        Returns:
            Kafka bootstrap servers from primary field or legacy aliases
        """
        return (
            self.kafka_bootstrap_servers
            or self.kafka_intelligence_bootstrap_servers
            or ""
        )

    def validate_required_services(self) -> list[str]:
        """
        Validate that required services are configured.

        Returns:
            List of validation error messages (empty if all valid)

        Example:
            >>> errors = settings.validate_required_services()
            >>> if errors:
            ...     for error in errors:
            ...         print(f"Configuration Error: {error}")
        """
        errors = []

        # Validate PostgreSQL password
        try:
            self.get_effective_postgres_password()
        except ValueError as e:
            errors.append(str(e))

        # Validate Kafka bootstrap servers
        if not self.get_effective_kafka_bootstrap_servers():
            errors.append(
                "Kafka bootstrap servers not configured. "
                "Set KAFKA_BOOTSTRAP_SERVERS in .env file"
            )

        # Validate agent registry exists (if configured)
        if self.agent_registry_path:
            registry_path = Path(self.agent_registry_path)
            if not registry_path.exists():
                errors.append(
                    f"Agent registry not found at: {self.agent_registry_path}. "
                    f"Set AGENT_REGISTRY_PATH environment variable or ensure file exists."
                )

        # Validate agent definitions directory exists (if configured)
        if self.agent_definitions_path:
            definitions_path = Path(self.agent_definitions_path)
            if not definitions_path.is_dir():
                errors.append(
                    f"Agent definitions directory not found at: {self.agent_definitions_path}. "
                    f"Set AGENT_DEFINITIONS_PATH environment variable or ensure directory exists."
                )

        return errors

    def log_configuration(
        self, logger_instance: Optional[logging.Logger] = None
    ) -> None:
        """
        Log configuration with sensitive values sanitized.

        Args:
            logger_instance: Logger to use (defaults to module logger)

        Example:
            >>> settings.log_configuration()
            INFO: Configuration loaded successfully
            INFO:   Environment: development
            INFO:   Kafka: 192.168.86.200:29092
            INFO:   PostgreSQL: 192.168.86.200:5436/omninode_bridge (password: ***)
        """
        log = logger_instance or logger

        log.info("=" * 80)
        log.info("OmniClaude Configuration")
        log.info("=" * 80)

        # External Services
        log.info("\nExternal Services:")
        log.info(f"  Archon Intelligence: {self.archon_intelligence_url}")
        log.info(f"  Archon Search: {self.archon_search_url}")
        log.info(f"  Archon Bridge: {self.archon_bridge_url}")
        log.info(f"  Archon MCP: {self.archon_mcp_url}")

        # Infrastructure
        log.info("\nShared Infrastructure:")
        log.info(f"  Kafka: {self.kafka_bootstrap_servers}")
        log.info(
            f"  PostgreSQL: {self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )
        log.info(f"  PostgreSQL User: {self.postgres_user}")
        log.info(
            f"  PostgreSQL Password: {'***' if self.postgres_password else '(not set)'}"
        )

        # Local Services
        log.info("\nLocal Services:")
        log.info(f"  Qdrant: {self.qdrant_url}")
        log.info(
            f"  Valkey: {self.valkey_url if self.valkey_url else '(not configured)'}"
        )
        log.info(
            f"  Intelligence Cache: {'enabled' if self.enable_intelligence_cache else 'disabled'}"
        )

        # API Keys
        log.info("\nAI Provider API Keys:")
        log.info(f"  Gemini: {'configured' if self.gemini_api_key else 'not set'}")
        log.info(f"  Z.ai: {'configured' if self.zai_api_key else 'not set'}")
        log.info(f"  OpenAI: {'configured' if self.openai_api_key else 'not set'}")

        # Feature Flags
        log.info("\nFeature Flags:")
        log.info(f"  Event-based Intelligence: {self.kafka_enable_intelligence}")
        log.info(f"  Pattern Quality Filter: {self.enable_pattern_quality_filter}")
        if self.enable_pattern_quality_filter:
            log.info(f"  Min Pattern Quality: {self.min_pattern_quality}")

        # Performance
        log.info("\nPerformance Configuration:")
        log.info(f"  Kafka Timeout: {self.kafka_request_timeout_ms}ms")
        log.info(f"  Routing Timeout: {self.routing_timeout_ms}ms")
        log.info(f"  Manifest Cache TTL: {self.manifest_cache_ttl_seconds}s")
        log.info(f"  Pattern Cache TTL: {self.cache_ttl_patterns}s")

        log.info("=" * 80)

    def to_dict_sanitized(self) -> dict:
        """
        Convert configuration to dictionary with sensitive values sanitized.

        Returns:
            Dictionary with configuration (passwords/keys replaced with ***)

        Example:
            >>> config_dict = settings.to_dict_sanitized()
            >>> print(config_dict['postgres_password'])
            ***
        """
        data = self.model_dump()

        # Sanitize sensitive fields
        sensitive_fields = [
            "postgres_password",
            "db_password",
            "omninode_bridge_postgres_password",
            "gemini_api_key",
            "google_api_key",
            "zai_api_key",
            "openai_api_key",
        ]

        for field in sensitive_fields:
            if data.get(field):
                data[field] = "***"

        # Sanitize Valkey URL (contains password)
        if data.get("valkey_url"):
            data["valkey_url"] = "***"

        return data


# =========================================================================
# SINGLETON INSTANCE
# =========================================================================

_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get or create singleton settings instance.

    This function implements the singleton pattern to ensure only one
    Settings instance is created and reused throughout the application.

    Returns:
        Settings instance

    Example:
        >>> from config import get_settings
        >>> settings = get_settings()
        >>> print(settings.postgres_host)
        192.168.86.200
    """
    global _settings
    if _settings is None:
        _settings = Settings()

        # Validate required services on first load
        errors = _settings.validate_required_services()
        if errors:
            error_msg = "\n".join(f"  - {error}" for error in errors)
            logger.error(f"Configuration validation failed:\n{error_msg}")
            # Note: We log but don't raise to allow partial configuration for testing
        else:
            logger.info("Configuration loaded and validated successfully")

    return _settings


def reload_settings() -> Settings:
    """
    Force reload of settings from environment.

    Useful for testing or when environment variables change at runtime.

    Returns:
        New Settings instance

    Example:
        >>> import os
        >>> os.environ['POSTGRES_PORT'] = '5432'
        >>> settings = reload_settings()
        >>> print(settings.postgres_port)
        5432
    """
    global _settings
    _settings = None
    return get_settings()
