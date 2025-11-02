"""
Intelligence Configuration Management.

Provides centralized configuration for event-based intelligence gathering with
environment variable support, feature flags, and validation.

Usage:
    >>> from agents.lib.config import IntelligenceConfig
    >>>
    >>> # Load from environment
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
1. Environment variables (highest)
2. Default values (lowest)

Environment Variables:
    KAFKA_BOOTSTRAP_SERVERS: Kafka broker addresses (default: localhost:29092)
    KAFKA_ENABLE_INTELLIGENCE: Enable event-based intelligence (default: true)
    KAFKA_REQUEST_TIMEOUT_MS: Request timeout in milliseconds (default: 5000)
    ENABLE_EVENT_BASED_DISCOVERY: Enable event discovery (default: true)
    ENABLE_FILESYSTEM_FALLBACK: Enable filesystem fallback (default: true)

Created: 2025-10-23
Reference: EVENT_INTELLIGENCE_INTEGRATION_PLAN.md Section 2.2
"""

import os
from typing import Any, Dict

from pydantic import BaseModel, Field, field_validator


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
        default_factory=lambda: os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"),
        description="Kafka bootstrap servers (set via KAFKA_BOOTSTRAP_SERVERS env var)",
    )

    kafka_enable_intelligence: bool = Field(
        default=True,
        description="Enable Kafka-based intelligence gathering",
    )

    kafka_request_timeout_ms: int = Field(
        default=5000,
        description="Default request timeout in milliseconds",
        ge=1000,
        le=60000,
    )

    kafka_pattern_discovery_timeout_ms: int = Field(
        default=5000,
        description="Pattern discovery timeout in milliseconds",
        ge=1000,
        le=60000,
    )

    kafka_code_analysis_timeout_ms: int = Field(
        default=10000,
        description="Code analysis timeout in milliseconds",
        ge=1000,
        le=120000,
    )

    kafka_consumer_group_prefix: str = Field(
        default="omniclaude-intelligence",
        description="Consumer group prefix for client isolation",
    )

    # =========================================================================
    # Feature Flags
    # =========================================================================

    enable_event_based_discovery: bool = Field(
        default=True,
        description="Enable event-based pattern discovery",
    )

    enable_filesystem_fallback: bool = Field(
        default=True,
        description="Enable fallback to built-in patterns on failure",
    )

    prefer_event_patterns: bool = Field(
        default=True,
        description="Prefer event-based patterns with higher confidence scores",
    )

    # =========================================================================
    # Topic Configuration
    # =========================================================================

    topic_code_analysis_requested: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-requested.v1",
        description="Topic for code analysis requests",
    )

    topic_code_analysis_completed: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-completed.v1",
        description="Topic for successful analysis responses",
    )

    topic_code_analysis_failed: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-failed.v1",
        description="Topic for failed analysis responses",
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
        Load configuration from environment variables.

        Environment variables override default values. All environment
        variables are optional and will fall back to defaults if not set.

        Returns:
            IntelligenceConfig with values from environment

        Example:
            >>> os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "kafka:9092"
            >>> config = IntelligenceConfig.from_env()
            >>> assert config.kafka_bootstrap_servers == "kafka:9092"
        """
        return cls(
            kafka_bootstrap_servers=os.getenv(
                "KAFKA_BOOTSTRAP_SERVERS", "localhost:29092"
            ),
            kafka_enable_intelligence=_parse_bool(
                os.getenv("KAFKA_ENABLE_INTELLIGENCE", "true")
            ),
            kafka_request_timeout_ms=_parse_int(
                os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000")
            ),
            kafka_pattern_discovery_timeout_ms=_parse_int(
                os.getenv("KAFKA_PATTERN_DISCOVERY_TIMEOUT_MS", "5000")
            ),
            kafka_code_analysis_timeout_ms=_parse_int(
                os.getenv("KAFKA_CODE_ANALYSIS_TIMEOUT_MS", "10000")
            ),
            kafka_consumer_group_prefix=os.getenv(
                "KAFKA_CONSUMER_GROUP_PREFIX", "omniclaude-intelligence"
            ),
            enable_event_based_discovery=_parse_bool(
                os.getenv("ENABLE_EVENT_BASED_DISCOVERY", "true")
            ),
            enable_filesystem_fallback=_parse_bool(
                os.getenv("ENABLE_FILESYSTEM_FALLBACK", "true")
            ),
            prefer_event_patterns=_parse_bool(
                os.getenv("PREFER_EVENT_PATTERNS", "true")
            ),
            topic_code_analysis_requested=os.getenv(
                "TOPIC_CODE_ANALYSIS_REQUESTED",
                "dev.archon-intelligence.intelligence.code-analysis-requested.v1",
            ),
            topic_code_analysis_completed=os.getenv(
                "TOPIC_CODE_ANALYSIS_COMPLETED",
                "dev.archon-intelligence.intelligence.code-analysis-completed.v1",
            ),
            topic_code_analysis_failed=os.getenv(
                "TOPIC_CODE_ANALYSIS_FAILED",
                "dev.archon-intelligence.intelligence.code-analysis-failed.v1",
            ),
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

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize configuration to dictionary.

        Returns:
            Dictionary with all configuration values
        """
        return self.model_dump()


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_bool(value: str) -> bool:
    """
    Parse boolean value from string.

    Args:
        value: String value (true/false, yes/no, 1/0)

    Returns:
        Boolean value
    """
    return value.lower() in ("true", "yes", "1", "on", "enabled")


def _parse_int(value: str) -> int:
    """
    Parse integer value from string.

    Args:
        value: String value

    Returns:
        Integer value

    Raises:
        ValueError: If value is not a valid integer
    """
    try:
        return int(value)
    except ValueError as e:
        raise ValueError(f"Invalid integer value: {value}") from e
