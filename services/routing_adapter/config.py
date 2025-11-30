"""
Routing Adapter Service Configuration.

Loads configuration from centralized settings (config.settings module).
Provides service-specific validation and configuration methods.

Configuration uses Pydantic Settings framework for type safety and validation.

See config/settings.py for all available configuration options.

Environment Variables:
    # Kafka Configuration
    KAFKA_BOOTSTRAP_SERVERS - Kafka broker addresses (default: 192.168.86.200:9092)

    # PostgreSQL Configuration (for logging routing decisions)
    POSTGRES_HOST - PostgreSQL host (default: 192.168.86.200)
    POSTGRES_PORT - PostgreSQL port (default: 5436)
    POSTGRES_DATABASE - Database name (default: omninode_bridge)
    POSTGRES_USER - Database user (default: postgres)
    POSTGRES_PASSWORD - Database password (required)

    # Service Configuration
    ROUTING_ADAPTER_PORT - Service HTTP port (default: 8055)
    ROUTING_ADAPTER_HOST - Service bind address (default: 0.0.0.0)
    HEALTH_CHECK_INTERVAL - Health check interval seconds (default: 30)

    # Agent Router Configuration
    AGENT_REGISTRY_PATH - Path to agent registry YAML (default: ~/.claude/agents/omniclaude/agent-registry.yaml)
    AGENT_DEFINITIONS_PATH - Path to agent definitions (default: ~/.claude/agents/omniclaude/)

    # Performance Configuration
    ROUTING_TIMEOUT_MS - Routing operation timeout (default: 5000)
    REQUEST_TIMEOUT_MS - Kafka request timeout (default: 5000)
    MAX_BATCH_SIZE - Max routing requests per batch (default: 100)

Implementation: Phase 2 - Pydantic Settings Migration
Note: As of Phase 2, configuration uses centralized Pydantic Settings framework.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from config import settings


logger = logging.getLogger(__name__)


class RoutingAdapterConfig:
    """Configuration container for routing adapter service."""

    def __init__(self):
        """
        Initialize configuration from centralized settings.

        Configuration is loaded from config.settings module for consistency.
        This class provides service-specific configuration and validation.
        """
        # Kafka Configuration
        self.kafka_bootstrap_servers = settings.kafka_bootstrap_servers

        # PostgreSQL Configuration
        self.postgres_host = settings.postgres_host
        self.postgres_port = settings.postgres_port  # Already int
        self.postgres_database = settings.postgres_database
        self.postgres_user = settings.postgres_user
        self.postgres_password = settings.get_effective_postgres_password()
        self.postgres_pool_min_size = settings.postgres_pool_min_size  # Already int
        self.postgres_pool_max_size = settings.postgres_pool_max_size  # Already int

        # Service Configuration
        self.service_port = settings.routing_adapter_port  # Already int
        self.service_host = settings.routing_adapter_host
        self.health_check_interval = settings.health_check_interval  # Already int

        # Agent Router Configuration
        # Uses settings.agent_registry_path which handles REGISTRY_PATH env var for Docker
        self.agent_registry_path = settings.agent_registry_path
        self.agent_definitions_path = settings.agent_definitions_path

        # Performance Configuration
        self.routing_timeout_ms = settings.routing_timeout_ms  # Already int
        self.request_timeout_ms = settings.kafka_request_timeout_ms  # Already int
        self.max_batch_size = settings.max_batch_size  # Already int
        self.cache_ttl_seconds = settings.cache_ttl_seconds  # Already int

        # Kafka Topics (service-specific, keep as is)
        self.topic_routing_request = "dev.routing-adapter.routing.request.v1"
        self.topic_routing_response = "dev.routing-adapter.routing.response.v1"
        self.topic_routing_failed = "dev.routing-adapter.routing.failed.v1"

        # Validate required configuration
        self._validate_config()

        # Log configuration (sanitized)
        self._log_config()

    def _validate_config(self) -> None:
        """
        Validate service-specific configuration.

        Note: Core configuration validation (types, formats) is handled by
        Pydantic Settings on startup. This validates service-specific requirements.

        Raises:
            ValueError: If service-specific configuration is invalid
        """
        errors = []

        # Validate agent registry path exists (service-specific requirement)
        if not Path(self.agent_registry_path).exists():
            errors.append(
                f"Agent registry not found at: {self.agent_registry_path}. "
                f"Set AGENT_REGISTRY_PATH environment variable."
            )

        # Validate agent definitions directory exists (service-specific requirement)
        if not Path(self.agent_definitions_path).is_dir():
            errors.append(
                f"Agent definitions directory not found at: {self.agent_definitions_path}. "
                f"Set AGENT_DEFINITIONS_PATH environment variable."
            )

        if errors:
            error_msg = "\n".join(f"  - {error}" for error in errors)
            raise ValueError(f"Service configuration validation failed:\n{error_msg}")

        # Note: Removed password/kafka validation - Pydantic handles this

    def _log_config(self) -> None:
        """Log configuration (with sanitization of sensitive values)."""
        logger.info(
            "Routing Adapter Configuration:",
            extra={
                "kafka_bootstrap_servers": self.kafka_bootstrap_servers,
                "postgres_host": self.postgres_host,
                "postgres_port": self.postgres_port,
                "postgres_database": self.postgres_database,
                "postgres_user": self.postgres_user,
                "postgres_password": "***" if self.postgres_password else "(not set)",
                "postgres_pool_min_size": self.postgres_pool_min_size,
                "postgres_pool_max_size": self.postgres_pool_max_size,
                "service_port": self.service_port,
                "service_host": self.service_host,
                "agent_registry_path": self.agent_registry_path,
                "agent_definitions_path": self.agent_definitions_path,
                "routing_timeout_ms": self.routing_timeout_ms,
                "topics": {
                    "request": self.topic_routing_request,
                    "response": self.topic_routing_response,
                    "failed": self.topic_routing_failed,
                },
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert configuration to dictionary for container registration.

        Returns:
            Dictionary of configuration values (with sensitive values sanitized)
        """
        return {
            # Kafka
            "kafka_bootstrap_servers": self.kafka_bootstrap_servers,
            # PostgreSQL
            "postgres_host": self.postgres_host,
            "postgres_port": self.postgres_port,
            "postgres_database": self.postgres_database,
            "postgres_user": self.postgres_user,
            "postgres_password": self.postgres_password,
            "postgres_pool_min_size": self.postgres_pool_min_size,
            "postgres_pool_max_size": self.postgres_pool_max_size,
            # Service
            "service_port": self.service_port,
            "service_host": self.service_host,
            "health_check_interval": self.health_check_interval,
            # Agent Router
            "agent_registry_path": self.agent_registry_path,
            "agent_definitions_path": self.agent_definitions_path,
            # Performance
            "routing_timeout_ms": self.routing_timeout_ms,
            "request_timeout_ms": self.request_timeout_ms,
            "max_batch_size": self.max_batch_size,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            # Topics
            "topic_routing_request": self.topic_routing_request,
            "topic_routing_response": self.topic_routing_response,
            "topic_routing_failed": self.topic_routing_failed,
        }

    def get(self, key: str, default: Optional[Any] = None) -> Any:
        """
        Get configuration value by key.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.to_dict().get(key, default)


# Singleton instance
_config: Optional[RoutingAdapterConfig] = None


def get_config() -> RoutingAdapterConfig:
    """
    Get or create singleton configuration instance.

    Returns:
        RoutingAdapterConfig instance
    """
    global _config
    if _config is None:
        _config = RoutingAdapterConfig()
    return _config
