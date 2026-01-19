#!/usr/bin/env python3
"""
Version Configuration for Autonomous Code Generation

Handles version isolation and feature flags for concurrent work streams.
Allows switching between legacy (Pydantic 1.x) and stable (Pydantic 2.x) implementations.

Configuration is loaded from centralized settings (config.settings module).
Call update_from_environment() to sync with latest settings values.

Note: As of Phase 2, configuration uses Pydantic Settings framework.
See config/settings.py for all available configuration options.
"""

from dataclasses import dataclass
from enum import Enum

from config import settings


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
    use_bridge_events: bool = (
        False  # Use omninode_bridge event infrastructure when ready
    )

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

    # Database configuration (production defaults - sync with config.settings)
    postgres_host: str = "192.168.86.200"
    postgres_port: int = 5436
    postgres_db: str = "omninode_bridge"
    postgres_user: str = "postgres"
    postgres_password: str = (
        ""  # REQUIRED: Set via POSTGRES_PASSWORD environment variable
    )

    # ONEX MCP Service configuration (production defaults - sync with config.settings)
    onex_mcp_host: str = "192.168.86.101"  # Set via ONEX_MCP_HOST environment variable
    onex_mcp_port: int = 8151

    # Redis configuration (production defaults - sync with config.settings)
    redis_host: str = "192.168.86.200"
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
        """
        Update configuration from centralized settings.

        Note: Configuration now loaded from config.settings module.
        This method provides backward compatibility for code that
        calls update_from_environment() explicitly.

        All type conversions and validations are handled by Pydantic Settings.
        """
        # Core library flags
        self.use_core_stable = settings.use_core_stable
        self.use_archon_events = settings.use_archon_events
        self.use_bridge_events = settings.use_bridge_events
        self.use_spi_validators = settings.use_spi_validators

        # Event-driven features
        self.enable_event_driven_analysis = settings.enable_event_driven_analysis
        self.enable_event_driven_validation = settings.enable_event_driven_validation
        self.enable_event_driven_patterns = settings.enable_event_driven_patterns

        # Database configuration
        self.postgres_host = settings.postgres_host
        self.postgres_port = settings.postgres_port  # Already int, no conversion needed
        self.postgres_db = settings.postgres_database  # Note: different name!
        self.postgres_user = settings.postgres_user
        self.postgres_password = settings.get_effective_postgres_password()

        # ONEX MCP Service configuration
        self.onex_mcp_host = settings.onex_mcp_host
        self.onex_mcp_port = settings.onex_mcp_port  # Already int

        # Redis configuration
        self.redis_host = settings.redis_host
        self.redis_port = settings.redis_port  # Already int

        # Kafka configuration
        self.kafka_bootstrap_servers = settings.kafka_bootstrap_servers
        self.consumer_group = (
            settings.kafka_consumer_group_prefix
        )  # Note: different name!

        # Quality gates
        self.quality_threshold = settings.quality_threshold  # Already float
        self.onex_compliance_threshold = (
            settings.onex_compliance_threshold
        )  # Already float
        self.require_human_review = settings.require_human_review  # Already bool

        # Timeouts
        self.analysis_timeout_seconds = settings.analysis_timeout_seconds  # Already int
        self.validation_timeout_seconds = (
            settings.validation_timeout_seconds
        )  # Already int

        # Note: No ValueError exception handling needed - Pydantic validates on settings load


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
