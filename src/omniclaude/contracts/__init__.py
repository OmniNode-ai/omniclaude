# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract-driven handler registration for omniclaude.

This package provides event-driven handler registration using the platform's
KafkaContractSource infrastructure (OMN-1654).

Handler contracts are read from contracts/handlers/**/contract.yaml and
published to Kafka for discovery by ServiceRuntimeHostProcess.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

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
