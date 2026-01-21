#!/usr/bin/env python3
"""
Code Generation Configuration

Centralizes configuration for Kafka and generation behavior with env overrides.

Migration Note (Phase 2):
    This file has been migrated from os.getenv() to Pydantic Settings framework.
    All configuration now comes from config.settings with automatic type validation.

Usage:
    from agents.lib.codegen_config import config

    # Access configuration with type safety
    print(config.kafka_bootstrap_servers)  # str
    print(config.generate_contracts)       # bool
    print(config.quality_threshold)        # float
"""

from config import settings


class CodegenConfig:
    """
    Code generation configuration proxy to Pydantic Settings.

    Provides backward-compatible interface while delegating to the
    centralized Settings class for type-safe configuration management.

    All values are loaded from environment variables and validated by Pydantic.
    """

    @property
    def kafka_bootstrap_servers(self) -> str:
        """Kafka bootstrap servers for code generation events."""
        return settings.kafka_bootstrap_servers

    @property
    def consumer_group(self) -> str:
        """Kafka consumer group for code generation service."""
        return settings.codegen_consumer_group

    # Generation control
    @property
    def generate_contracts(self) -> bool:
        """Enable automatic contract generation."""
        return settings.codegen_generate_contracts

    @property
    def generate_models(self) -> bool:
        """Enable automatic model generation."""
        return settings.codegen_generate_models

    @property
    def generate_enums(self) -> bool:
        """Enable automatic enum generation."""
        return settings.codegen_generate_enums

    @property
    def generate_business_logic(self) -> bool:
        """Enable business logic generation (starts with stubs)."""
        return settings.codegen_generate_business_logic

    @property
    def generate_tests(self) -> bool:
        """Enable automatic test generation."""
        return settings.codegen_generate_tests

    # Quality gates
    @property
    def quality_threshold(self) -> float:
        """Minimum quality threshold for code generation (0.0-1.0)."""
        return settings.quality_threshold

    @property
    def onex_compliance_threshold(self) -> float:
        """Minimum ONEX compliance threshold (0.0-1.0)."""
        return settings.onex_compliance_threshold

    @property
    def require_human_review(self) -> bool:
        """Require human review for generated code."""
        return settings.require_human_review

    # Intelligence timeouts (seconds)
    @property
    def analysis_timeout_seconds(self) -> int:
        """Code analysis timeout in seconds."""
        return settings.analysis_timeout_seconds

    @property
    def validation_timeout_seconds(self) -> int:
        """Validation timeout in seconds."""
        return settings.validation_timeout_seconds

    # Mixin configuration
    @property
    def auto_select_mixins(self) -> bool:
        """Automatically select appropriate mixins for generated code."""
        return settings.codegen_auto_select_mixins

    @property
    def mixin_confidence_threshold(self) -> float:
        """Minimum confidence threshold for mixin selection (0.0-1.0)."""
        return settings.codegen_mixin_confidence_threshold


# Singleton instance for backward compatibility
config = CodegenConfig()
