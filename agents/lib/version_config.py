#!/usr/bin/env python3
"""
Version Configuration for Autonomous Code Generation

Handles version isolation and feature flags for concurrent work streams.
Allows switching between legacy (Pydantic 1.x) and stable (Pydantic 2.x) implementations.
"""

from dataclasses import dataclass
from enum import Enum


class ImplementationMode(Enum):
    """Implementation modes for different components"""

    LEGACY = "legacy"  # Use copied omniagent code with Pydantic 1.x
    STABLE = "stable"  # Use stable core library with Pydantic 2.x
    ADAPTER = "adapter"  # Use adapter layer for compatibility


@dataclass
class VersionConfig:
    """Configuration for version management and feature flags"""

    # Core library dependencies
    use_core_stable: bool = True  # Use omnibase_core as dependency
    use_spi_validators: bool = True  # Use omnibase_spi as dependency
    use_archon_events: bool = False  # Use omniarchon event handlers when ready
    use_bridge_events: bool = False  # Use omninode_bridge event infrastructure when ready

    # Implementation modes
    prd_parser_mode: ImplementationMode = ImplementationMode.LEGACY
    task_decomposition_mode: ImplementationMode = ImplementationMode.LEGACY
    template_engine_mode: ImplementationMode = ImplementationMode.ADAPTER
    contract_generation_mode: ImplementationMode = ImplementationMode.ADAPTER
    node_generation_mode: ImplementationMode = ImplementationMode.ADAPTER

    # Local template system (until omnibase_infra is ported)
    use_local_templates: bool = True
    template_directory: str = "agents/templates"

    # Event-driven features
    enable_event_driven_analysis: bool = False
    enable_event_driven_validation: bool = False
    enable_event_driven_patterns: bool = False

    # Quality gates
    quality_threshold: float = 0.8
    onex_compliance_threshold: float = 0.7
    require_human_review: bool = True

    # Intelligence timeouts
    analysis_timeout_seconds: int = 30
    validation_timeout_seconds: int = 20

    # Mixin configuration
    auto_select_mixins: bool = True
    mixin_confidence_threshold: float = 0.7

    # Database configuration
    postgres_host: str = "localhost"
    postgres_port: int = 5436
    postgres_db: str = "omninode_bridge"
    postgres_user: str = "postgres"
    postgres_password: str = ""  # REQUIRED: Set via POSTGRES_PASSWORD environment variable

    # ONEX MCP Service configuration
    onex_mcp_host: str = "localhost"  # Set via ONEX_MCP_HOST environment variable
    onex_mcp_port: int = 8151

    # Redis configuration
    redis_host: str = "localhost"
    redis_port: int = 6379

    # Kafka configuration
    kafka_bootstrap_servers: str = "omninode-bridge-redpanda:9092"
    consumer_group: str = "omniclaude-codegen"

    # Generation control
    generate_contracts: bool = True
    generate_models: bool = True
    generate_enums: bool = True
    generate_business_logic: bool = False  # Start with stubs
    generate_tests: bool = True

    def get_implementation_mode(self, component: str) -> ImplementationMode:
        """Get implementation mode for a specific component"""
        mode_map = {
            "prd_parser": self.prd_parser_mode,
            "task_decomposition": self.task_decomposition_mode,
            "template_engine": self.template_engine_mode,
            "contract_generation": self.contract_generation_mode,
            "node_generation": self.node_generation_mode,
        }
        return mode_map.get(component, ImplementationMode.LEGACY)

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled"""
        feature_map = {
            "event_driven_analysis": self.enable_event_driven_analysis,
            "event_driven_validation": self.enable_event_driven_validation,
            "event_driven_patterns": self.enable_event_driven_patterns,
            "local_templates": self.use_local_templates,
            "core_stable": self.use_core_stable,
            "archon_events": self.use_archon_events,
            "bridge_events": self.use_bridge_events,
            "spi_validators": self.use_spi_validators,
        }
        return feature_map.get(feature, False)

    def update_from_environment(self):
        """Update configuration from environment variables"""
        import os

        # Core library flags
        self.use_core_stable = os.getenv("USE_CORE_STABLE", "false").lower() == "true"
        self.use_archon_events = os.getenv("USE_ARCHON_EVENTS", "false").lower() == "true"
        self.use_bridge_events = os.getenv("USE_BRIDGE_EVENTS", "false").lower() == "true"
        self.use_spi_validators = os.getenv("USE_SPI_VALIDATORS", "false").lower() == "true"

        # Event-driven features
        self.enable_event_driven_analysis = os.getenv("ENABLE_EVENT_DRIVEN_ANALYSIS", "false").lower() == "true"
        self.enable_event_driven_validation = os.getenv("ENABLE_EVENT_DRIVEN_VALIDATION", "false").lower() == "true"
        self.enable_event_driven_patterns = os.getenv("ENABLE_EVENT_DRIVEN_PATTERNS", "false").lower() == "true"

        # Database configuration
        self.postgres_host = os.getenv("POSTGRES_HOST", self.postgres_host)
        try:
            self.postgres_port = int(os.getenv("POSTGRES_PORT", str(self.postgres_port)))
        except ValueError as e:
            raise ValueError(f"Invalid POSTGRES_PORT value. Must be a valid integer: {e}")
        self.postgres_db = os.getenv("POSTGRES_DB", self.postgres_db)
        self.postgres_user = os.getenv("POSTGRES_USER", self.postgres_user)
        self.postgres_password = os.getenv("POSTGRES_PASSWORD", self.postgres_password)

        # ONEX MCP Service configuration
        self.onex_mcp_host = os.getenv("ONEX_MCP_HOST", self.onex_mcp_host)
        try:
            self.onex_mcp_port = int(os.getenv("ONEX_MCP_PORT", str(self.onex_mcp_port)))
        except ValueError as e:
            raise ValueError(f"Invalid ONEX_MCP_PORT value. Must be a valid integer: {e}")

        # Redis configuration
        self.redis_host = os.getenv("REDIS_HOST", self.redis_host)
        try:
            self.redis_port = int(os.getenv("REDIS_PORT", str(self.redis_port)))
        except ValueError as e:
            raise ValueError(f"Invalid REDIS_PORT value. Must be a valid integer: {e}")

        # Kafka configuration
        self.kafka_bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", self.kafka_bootstrap_servers)
        self.consumer_group = os.getenv("CONSUMER_GROUP", self.consumer_group)

        # Quality gates
        self.quality_threshold = float(os.getenv("QUALITY_THRESHOLD", str(self.quality_threshold)))
        self.onex_compliance_threshold = float(
            os.getenv("ONEX_COMPLIANCE_THRESHOLD", str(self.onex_compliance_threshold))
        )
        self.require_human_review = os.getenv("REQUIRE_HUMAN_REVIEW", "true").lower() == "true"

        # Timeouts
        self.analysis_timeout_seconds = int(os.getenv("ANALYSIS_TIMEOUT_SECONDS", str(self.analysis_timeout_seconds)))
        self.validation_timeout_seconds = int(
            os.getenv("VALIDATION_TIMEOUT_SECONDS", str(self.validation_timeout_seconds))
        )


# Global configuration instance
config = VersionConfig()

# Update from environment on import
config.update_from_environment()


def get_config() -> VersionConfig:
    """Get the global configuration instance"""
    return config


def update_config(**kwargs) -> None:
    """Update configuration with new values"""
    global config
    for key, value in kwargs.items():
        if hasattr(config, key):
            setattr(config, key, value)
