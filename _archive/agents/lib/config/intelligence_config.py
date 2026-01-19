"""
Intelligence Configuration Management.

Provides centralized configuration for event-based intelligence gathering with
environment variable support, feature flags, and validation.

Usage:
    >>> from agents.lib.config import IntelligenceConfig
    >>>
    >>> # Load from environment (uses centralized settings)
    >>> config = IntelligenceConfig.from_env()
    >>> config.validate_config()
    >>>
    >>> # Check if event discovery is enabled
    >>> if config.is_event_discovery_enabled():
    ...     client = IntelligenceEventClient(config.kafka_bootstrap_servers)
    ...
    >>> # Get appropriate bootstrap servers
    >>> servers = config.get_bootstrap_servers()

Configuration precedence:
1. System environment variables (highest)
2. .env.{ENVIRONMENT} file (environment-specific)
3. .env file (default/fallback)
4. Default values in Settings class (lowest)

Environment Variables:
    KAFKA_BOOTSTRAP_SERVERS: Kafka broker addresses (default: 192.168.86.200:29092)
    KAFKA_ENABLE_INTELLIGENCE: Enable event-based intelligence (default: true)
    KAFKA_REQUEST_TIMEOUT_MS: Request timeout in milliseconds (default: 5000)
    KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS: Pattern discovery timeout (default: 5000)
    KAFKA_CODE_ANALYSIS_TIMEOUT_MS: Code analysis timeout (default: 10000)
    ENABLE_EVENT_BASED_DISCOVERY: Enable event discovery (default: true)
    ENABLE_FILESYSTEM_FALLBACK: Enable filesystem fallback (default: true)

Created: 2025-10-23
Updated: 2025-11-06 (Phase 2: Migrated to Pydantic Settings)
Reference: EVENT_INTELLIGENCE_INTEGRATION_PLAN.md Section 2.2
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator

# Lazy import of settings to avoid circular dependency
# Settings is loaded on first access, not at module import time
_settings_cache: Any = None


def _get_settings() -> Any:
    """Lazy import settings from global config package (cached)."""
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    # Use importlib to load settings from absolute file path
    # This bypasses sys.path resolution and avoids conflicts with local config package
    import importlib.util
    from pathlib import Path as _Path

    _project_root = _Path(__file__).parent.parent.parent.parent
    _settings_file = _project_root / "config" / "settings.py"

    # Load settings module directly from file
    spec = importlib.util.spec_from_file_location(
        "_global_config_settings", _settings_file
    )
    if spec is None:
        raise RuntimeError(f"Could not load spec from {_settings_file}")
    settings_module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Spec loader is None for {_settings_file}")
    spec.loader.exec_module(settings_module)

    # Get settings singleton
    _settings_cache = settings_module.get_settings()
    return _settings_cache


# Create a proxy object that delegates to the lazy-loaded settings
class _SettingsProxy:
    def __getattr__(self, name):
        return getattr(_get_settings(), name)


settings = _SettingsProxy()


class IntelligenceConfig(BaseModel):
    """
    Configuration for intelligence gathering system.

    This configuration manages both event-based intelligence discovery and
    fallback mechanisms. It supports environment variable overrides and
    provides validation for configuration consistency.

    Attributes:
        kafka_bootstrap_servers: Kafka broker addresses
        kafka_enable_intelligence: Enable Kafka-based intelligence
        kafka_request_timeout_ms: Request timeout in milliseconds
        kafka_pattern_discovery_timeout_ms: Pattern discovery timeout
        kafka_code_analysis_timeout_ms: Code analysis timeout
        kafka_consumer_group_prefix: Consumer group prefix for isolation
        enable_event_based_discovery: Enable event-based pattern discovery
        enable_filesystem_fallback: Enable fallback to built-in patterns
        prefer_event_patterns: Prefer event-based patterns (higher confidence)
        topic_code_analysis_requested: Request topic name
        topic_code_analysis_completed: Success response topic name
        topic_code_analysis_failed: Error response topic name
    """

    # =========================================================================
    # Kafka Configuration
    # =========================================================================

    kafka_bootstrap_servers: str = Field(
        default_factory=lambda: settings.kafka_bootstrap_servers,
        description="Kafka bootstrap servers (loaded from centralized settings)",
    )

    kafka_enable_intelligence: bool = Field(
        default_factory=lambda: settings.kafka_enable_intelligence,
        description="Enable Kafka-based intelligence gathering (loaded from centralized settings)",
    )

    kafka_request_timeout_ms: int = Field(
        default_factory=lambda: settings.kafka_request_timeout_ms,
        description="Default request timeout in milliseconds (loaded from centralized settings)",
        ge=1000,
        le=60000,
    )

    kafka_pattern_discovery_timeout_ms: int = Field(
        default_factory=lambda: settings.kafka_pattern_discovery_timeout_ms,
        description="Pattern discovery timeout in milliseconds (loaded from centralized settings)",
        ge=1000,
        le=60000,
    )

    kafka_code_analysis_timeout_ms: int = Field(
        default_factory=lambda: settings.kafka_code_analysis_timeout_ms,
        description="Code analysis timeout in milliseconds (loaded from centralized settings)",
        ge=1000,
        le=120000,
    )

    kafka_consumer_group_prefix: str = Field(
        default_factory=lambda: settings.kafka_consumer_group_prefix,
        description="Consumer group prefix for client isolation (loaded from centralized settings)",
    )

    # =========================================================================
    # Feature Flags
    # =========================================================================

    enable_event_based_discovery: bool = Field(
        default_factory=lambda: settings.enable_event_based_discovery,
        description="Enable event-based pattern discovery (loaded from centralized settings)",
    )

    enable_filesystem_fallback: bool = Field(
        default_factory=lambda: settings.enable_filesystem_fallback,
        description="Enable fallback to built-in patterns on failure (loaded from centralized settings)",
    )

    prefer_event_patterns: bool = Field(
        default_factory=lambda: settings.prefer_event_patterns,
        description="Prefer event-based patterns with higher confidence scores (loaded from centralized settings)",
    )

    # =========================================================================
    # Topic Configuration
    # =========================================================================

    topic_code_analysis_requested: str = Field(
        default_factory=lambda: settings.topic_code_analysis_requested,
        description="Topic for code analysis requests (loaded from centralized settings)",
    )

    topic_code_analysis_completed: str = Field(
        default_factory=lambda: settings.topic_code_analysis_completed,
        description="Topic for successful analysis responses (loaded from centralized settings)",
    )

    topic_code_analysis_failed: str = Field(
        default_factory=lambda: settings.topic_code_analysis_failed,
        description="Topic for failed analysis responses (loaded from centralized settings)",
    )

    # =========================================================================
    # Validators
    # =========================================================================

    @field_validator("kafka_bootstrap_servers")
    @classmethod
    def validate_bootstrap_servers(cls, v: str) -> str:
        """Validate Kafka bootstrap servers format."""
        if not v or not v.strip():
            raise ValueError("kafka_bootstrap_servers cannot be empty")

        # Check for basic host:port format
        servers = [s.strip() for s in v.split(",")]
        for server in servers:
            if ":" not in server:
                raise ValueError(
                    f"Invalid server format '{server}'. Expected 'host:port'"
                )
            host, port = server.rsplit(":", 1)
            if not host or not port:
                raise ValueError(
                    f"Invalid server format '{server}'. Expected 'host:port'"
                )
            try:
                port_int = int(port)
                if port_int < 1 or port_int > 65535:
                    raise ValueError(f"Port {port_int} out of valid range (1-65535)")
            except ValueError as e:
                raise ValueError(f"Invalid port in '{server}': {e}") from e

        return v

    @field_validator("kafka_consumer_group_prefix")
    @classmethod
    def validate_consumer_group_prefix(cls, v: str) -> str:
        """Validate consumer group prefix is not empty."""
        if not v or not v.strip():
            raise ValueError("kafka_consumer_group_prefix cannot be empty")
        return v.strip()

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_env(cls) -> "IntelligenceConfig":
        """
        Load configuration from centralized settings.

        This method creates an IntelligenceConfig instance using values from
        the centralized Pydantic Settings framework, accessing the singleton
        settings instance directly.

        Configuration is loaded with the following precedence:
        1. System environment variables (highest priority)
        2. .env.{ENVIRONMENT} file (environment-specific overrides)
        3. .env file (default/fallback)
        4. Default values in Settings class (lowest priority)

        Returns:
            IntelligenceConfig with values from centralized settings

        Example:
            >>> config = IntelligenceConfig.from_env()
            >>> print(config.kafka_bootstrap_servers)
            192.168.86.200:29092
        """
        return cls(
            kafka_bootstrap_servers=settings.kafka_bootstrap_servers,
            kafka_enable_intelligence=settings.kafka_enable_intelligence,
            kafka_request_timeout_ms=settings.kafka_request_timeout_ms,
            kafka_pattern_discovery_timeout_ms=settings.kafka_pattern_discovery_timeout_ms,
            kafka_code_analysis_timeout_ms=settings.kafka_code_analysis_timeout_ms,
            kafka_consumer_group_prefix=settings.kafka_consumer_group_prefix,
            enable_event_based_discovery=settings.enable_event_based_discovery,
            enable_filesystem_fallback=settings.enable_filesystem_fallback,
            prefer_event_patterns=settings.prefer_event_patterns,
            topic_code_analysis_requested=settings.topic_code_analysis_requested,
            topic_code_analysis_completed=settings.topic_code_analysis_completed,
            topic_code_analysis_failed=settings.topic_code_analysis_failed,
        )

    # =========================================================================
    # Validation & Utility Methods
    # =========================================================================

    def validate_config(self) -> None:
        """
        Validate configuration consistency.

        Checks:
        - If event discovery is disabled but no fallback is enabled
        - Timeout values are reasonable
        - Topic names are not empty

        Raises:
            ValueError: If configuration is inconsistent
        """
        # Check fallback configuration
        if (
            not self.enable_event_based_discovery
            and not self.enable_filesystem_fallback
        ):
            raise ValueError(
                "At least one intelligence source must be enabled: "
                "enable_event_based_discovery or enable_filesystem_fallback"
            )

        # Validate topic names
        if not self.topic_code_analysis_requested.strip():
            raise ValueError("topic_code_analysis_requested cannot be empty")
        if not self.topic_code_analysis_completed.strip():
            raise ValueError("topic_code_analysis_completed cannot be empty")
        if not self.topic_code_analysis_failed.strip():
            raise ValueError("topic_code_analysis_failed cannot be empty")

    def is_event_discovery_enabled(self) -> bool:
        """
        Check if event-based discovery should be used.

        Returns:
            True if both kafka_enable_intelligence and
            enable_event_based_discovery are True
        """
        return self.kafka_enable_intelligence and self.enable_event_based_discovery

    def get_bootstrap_servers(self) -> str:
        """
        Get Kafka bootstrap servers.

        Returns:
            Bootstrap servers string (comma-separated)
        """
        return self.kafka_bootstrap_servers

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize configuration to dictionary.

        Returns:
            Dictionary with all configuration values
        """
        return self.model_dump()
