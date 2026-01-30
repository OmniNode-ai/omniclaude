# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Runtime wiring and service registration for omniclaude.

This package provides the manual service wiring for the MVP implementation.
A follow-up ticket will implement contract-driven handler registration where
the loader reads handler contracts and auto-registers handlers.

Exported:
    wire_omniclaude_services: Async function to register handlers with container
    publish_handler_contracts: Async function to publish handler contracts to Kafka
    PublishResult: Result dataclass with published and failed lists
"""

from .wiring import PublishResult, publish_handler_contracts, wire_omniclaude_services

__all__ = [
    "PublishResult",
    "publish_handler_contracts",
    "wire_omniclaude_services",
]
