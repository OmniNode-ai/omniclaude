#!/usr/bin/env python3
"""
Code Generation Configuration

Centralizes configuration for Kafka and generation behavior with env overrides.
"""

import os
from dataclasses import dataclass


@dataclass
class CodegenConfig:
    # Kafka configuration
    kafka_bootstrap_servers: str = "omninode-bridge-redpanda:9092"
    consumer_group: str = "omniclaude-codegen"

    # Generation control
    generate_contracts: bool = True
    generate_models: bool = True
    generate_enums: bool = True
    generate_business_logic: bool = False  # Start with stubs
    generate_tests: bool = True

    # Quality gates
    quality_threshold: float = 0.8
    onex_compliance_threshold: float = 0.7
    require_human_review: bool = True

    # Intelligence timeouts (seconds)
    analysis_timeout_seconds: int = 30
    validation_timeout_seconds: int = 20

    # Mixin configuration
    auto_select_mixins: bool = True
    mixin_confidence_threshold: float = 0.7

    def load_env_overrides(self) -> None:
        self.kafka_bootstrap_servers = os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", self.kafka_bootstrap_servers
        )
        self.consumer_group = os.getenv("CODEGEN_CONSUMER_GROUP", self.consumer_group)
        self.generate_contracts = (
            os.getenv(
                "CODEGEN_GENERATE_CONTRACTS", str(self.generate_contracts)
            ).lower()
            == "true"
        )
        self.generate_models = (
            os.getenv("CODEGEN_GENERATE_MODELS", str(self.generate_models)).lower()
            == "true"
        )
        self.generate_enums = (
            os.getenv("CODEGEN_GENERATE_ENUMS", str(self.generate_enums)).lower()
            == "true"
        )
        self.generate_business_logic = (
            os.getenv(
                "CODEGEN_GENERATE_BUSINESS_LOGIC", str(self.generate_business_logic)
            ).lower()
            == "true"
        )
        self.generate_tests = (
            os.getenv("CODEGEN_GENERATE_TESTS", str(self.generate_tests)).lower()
            == "true"
        )
        self.quality_threshold = float(
            os.getenv("CODEGEN_QUALITY_THRESHOLD", str(self.quality_threshold))
        )
        self.onex_compliance_threshold = float(
            os.getenv(
                "CODEGEN_ONEX_COMPLIANCE_THRESHOLD", str(self.onex_compliance_threshold)
            )
        )
        self.require_human_review = (
            os.getenv(
                "CODEGEN_REQUIRE_HUMAN_REVIEW", str(self.require_human_review)
            ).lower()
            == "true"
        )
        self.analysis_timeout_seconds = int(
            os.getenv(
                "CODEGEN_ANALYSIS_TIMEOUT_SECONDS", str(self.analysis_timeout_seconds)
            )
        )
        self.validation_timeout_seconds = int(
            os.getenv(
                "CODEGEN_VALIDATION_TIMEOUT_SECONDS",
                str(self.validation_timeout_seconds),
            )
        )
        self.auto_select_mixins = (
            os.getenv(
                "CODEGEN_AUTO_SELECT_MIXINS", str(self.auto_select_mixins)
            ).lower()
            == "true"
        )
        self.mixin_confidence_threshold = float(
            os.getenv(
                "CODEGEN_MIXIN_CONFIDENCE_THRESHOLD",
                str(self.mixin_confidence_threshold),
            )
        )


config = CodegenConfig()
config.load_env_overrides()
