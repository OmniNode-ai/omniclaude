"""
Routing Adapter Service Configuration.

Loads configuration from environment variables with sensible defaults.
Follows ONEX v2.0 patterns for configuration management.

Environment Variables:
    # Kafka Configuration
    KAFKA_BOOTSTRAP_SERVERS - Kafka broker addresses (default: 192.168.86.200:29092)

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
    AGENT_REGISTRY_PATH - Path to agent registry YAML (default: ~/.claude/agent-definitions/agent-registry.yaml)
    AGENT_DEFINITIONS_PATH - Path to agent definitions (default: ~/.claude/agent-definitions/)

    # Performance Configuration
    ROUTING_TIMEOUT_MS - Routing operation timeout (default: 5000)
    REQUEST_TIMEOUT_MS - Kafka request timeout (default: 5000)
    MAX_BATCH_SIZE - Max routing requests per batch (default: 100)

Implementation: Phase 1 - Event-Driven Routing Adapter
"""

import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RoutingAdapterConfig:
    """Configuration container for routing adapter service."""

    def __init__(self):
        """Initialize configuration from environment variables."""
        # Kafka Configuration
        self.kafka_bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092"
        )

        # PostgreSQL Configuration
        self.postgres_host = os.getenv("POSTGRES_HOST", "192.168.86.200")
        self.postgres_port = int(os.getenv("POSTGRES_PORT", "5436"))
        self.postgres_database = os.getenv("POSTGRES_DATABASE", "omninode_bridge")
        self.postgres_user = os.getenv("POSTGRES_USER", "postgres")
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", "")
        self.postgres_pool_min_size = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "2"))
        self.postgres_pool_max_size = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "10"))

        # Service Configuration
        self.service_port = int(os.getenv("ROUTING_ADAPTER_PORT", "8055"))
        self.service_host = os.getenv("ROUTING_ADAPTER_HOST", "0.0.0.0")
        self.health_check_interval = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))

        # Agent Router Configuration
        home_dir = Path.home()
        self.agent_registry_path = os.getenv(
            "AGENT_REGISTRY_PATH",
            str(home_dir / ".claude" / "agent-definitions" / "agent-registry.yaml"),
        )
        self.agent_definitions_path = os.getenv(
            "AGENT_DEFINITIONS_PATH", str(home_dir / ".claude" / "agent-definitions")
        )

        # Performance Configuration
        self.routing_timeout_ms = int(os.getenv("ROUTING_TIMEOUT_MS", "5000"))
        self.request_timeout_ms = int(os.getenv("REQUEST_TIMEOUT_MS", "5000"))
        self.max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "100"))
        self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

        # Kafka Topics
        self.topic_routing_request = "dev.routing-adapter.routing.request.v1"
        self.topic_routing_response = "dev.routing-adapter.routing.response.v1"
        self.topic_routing_failed = "dev.routing-adapter.routing.failed.v1"

        # Validate required configuration
        self._validate_config()

        # Log configuration (sanitized)
        self._log_config()

    def _validate_config(self) -> None:
        """
        Validate required configuration values.

        Raises:
            ValueError: If required configuration is missing or invalid
        """
        errors = []

        # Validate PostgreSQL password
        if not self.postgres_password:
            errors.append("POSTGRES_PASSWORD environment variable is required")

        # Validate Kafka bootstrap servers
        if not self.kafka_bootstrap_servers:
            errors.append("KAFKA_BOOTSTRAP_SERVERS environment variable is required")

        # Validate agent registry path exists
        if not Path(self.agent_registry_path).exists():
            errors.append(
                f"Agent registry not found at: {self.agent_registry_path}. "
                f"Set AGENT_REGISTRY_PATH environment variable."
            )

        # Validate agent definitions directory exists
        if not Path(self.agent_definitions_path).is_dir():
            errors.append(
                f"Agent definitions directory not found at: {self.agent_definitions_path}. "
                f"Set AGENT_DEFINITIONS_PATH environment variable."
            )

        if errors:
            error_msg = "\n".join(f"  - {error}" for error in errors)
            raise ValueError(f"Configuration validation failed:\n{error_msg}")

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
