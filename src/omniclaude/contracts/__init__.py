# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract-driven handler registration for omniclaude.

This package provides event-driven handler registration using the platform's
KafkaContractSource infrastructure (OMN-1654) and ServiceContractPublisher
from omnibase_infra (OMN-1812).

Handler contracts are read from contracts/handlers/**/contract.yaml and
published to Kafka for discovery by ServiceRuntimeHostProcess.

Tickets:
    - OMN-1605: Implement contract-driven handler registration loader
    - OMN-1812: Migrate to ServiceContractPublisher from omnibase_infra

Migration Note (v3.2.0):
    Contract publishing now uses ServiceContractPublisher from omnibase_infra,
    enforcing ARCH-002 ("Runtime owns all Kafka plumbing"). For contract
    configuration and result types, use the canonical models from omnibase_infra:

    - ModelContractPublisherConfig (replaces local ContractPublisherConfig)
    - ModelPublishResult (replaces local PublishResult)
    - ModelContractError (replaces local ContractError)
    - ModelInfraError (replaces local InfraError)

    Import from:
        from omnibase_infra.services.contract_publisher import (
            ModelContractPublisherConfig,
            ModelPublishResult,
            ModelContractError,
            ModelInfraError,
        )

Usage:
    from omniclaude.runtime.wiring import wire_omniclaude_services

    # During application bootstrap
    container = ModelONEXContainer(...)
    await wire_omniclaude_services(container)
"""

from __future__ import annotations

# Re-export wiring functions for convenience
from omniclaude.runtime.wiring import (
    publish_handler_contracts,
    wire_omniclaude_services,
)

__all__ = [
    "publish_handler_contracts",
    "wire_omniclaude_services",
]
