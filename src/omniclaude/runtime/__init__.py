# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Runtime wiring and service registration for omniclaude.

This package provides the manual service wiring for the MVP implementation.
A follow-up ticket will implement contract-driven handler registration where
the loader reads handler contracts and auto-registers handlers.

Exported:
    wire_omniclaude_services: Async function to register handlers with container
    publish_handler_contracts: Async function to publish handler contracts to Kafka
    ContractPublisherConfig: Pydantic config for explicit source configuration
    ContractError: Dataclass for contract-level errors (non-fatal)
    InfraError: Dataclass for infrastructure errors (fatal by default)
    PublishResult: Result dataclass with published list and separated error types

Exceptions:
    ContractPublisherError: Base exception for contract publishing errors
    ContractSourceNotConfiguredError: Raised when no contract source is configured
    ContractPublishingInfraError: Raised on infrastructure failures (fail_fast=True)
    NoContractsFoundError: Raised when no contracts found (allow_zero_contracts=False)
"""

from .contract_models import (
    ContractError,
    ContractPublisherConfig,
    InfraError,
    PublishResult,
)
from .exceptions import (
    ContractPublisherError,
    ContractPublishingInfraError,
    ContractSourceNotConfiguredError,
    NoContractsFoundError,
)
from .wiring import publish_handler_contracts, wire_omniclaude_services

__all__ = [
    # Configuration
    "ContractPublisherConfig",
    # Error types (dataclasses)
    "ContractError",
    "InfraError",
    # Result type
    "PublishResult",
    # Wiring functions
    "publish_handler_contracts",
    "wire_omniclaude_services",
    # Exceptions
    "ContractPublisherError",
    "ContractSourceNotConfiguredError",
    "ContractPublishingInfraError",
    "NoContractsFoundError",
]
