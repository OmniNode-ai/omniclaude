# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Runtime wiring and service registration for omniclaude.

This package provides service wiring that delegates to omnibase_infra's
ServiceContractPublisher for contract-driven handler registration.

Ticket: OMN-1812 - Migrate wiring.py to use ServiceContractPublisher from omnibase_infra

Architecture (ARCH-002):
    Runtime owns all Kafka plumbing. All contract publishing functionality
    is provided by omnibase_infra.services.contract_publisher.

Exported:
    wire_omniclaude_services: Async function to register handlers with container
    publish_handler_contracts: Async function to publish handler contracts to Kafka

Configuration (re-exported from omnibase_infra):
    ModelContractPublisherConfig: Pydantic config for explicit source configuration

Error Types (re-exported from omnibase_infra):
    ModelContractError: Dataclass for contract-level errors (non-fatal)
    ModelInfraError: Dataclass for infrastructure errors (fatal by default)

Result Types (re-exported from omnibase_infra):
    ModelPublishResult: Result dataclass with published list and separated error types

Exceptions (re-exported from omnibase_infra):
    ContractPublisherError: Base exception for contract publishing errors
    ContractSourceNotConfiguredError: Raised when no contract source is configured
    ContractPublishingInfraError: Raised on infrastructure failures (fail_fast=True)
    NoContractsFoundError: Raised when no contracts found (allow_zero_contracts=False)
"""

# Re-export configuration and result types from omnibase_infra
from omnibase_infra.services.contract_publisher import (
    ContractPublisherError,
    ContractPublishingInfraError,
    ContractSourceNotConfiguredError,
    ModelContractError,
    ModelContractPublisherConfig,
    ModelInfraError,
    ModelPublishResult,
    NoContractsFoundError,
)

# Export wiring functions
from .wiring import publish_handler_contracts, wire_omniclaude_services

__all__ = [
    # Configuration
    "ModelContractPublisherConfig",
    # Error types (dataclasses from infra)
    "ModelContractError",
    "ModelInfraError",
    # Result type
    "ModelPublishResult",
    # Wiring functions
    "publish_handler_contracts",
    "wire_omniclaude_services",
    # Exceptions (from infra)
    "ContractPublisherError",
    "ContractSourceNotConfiguredError",
    "ContractPublishingInfraError",
    "NoContractsFoundError",
]
