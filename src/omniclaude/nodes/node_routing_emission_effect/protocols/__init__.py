# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeRoutingEmissionEffect node.

This package defines the protocol interface for routing emission backends.

Exported:
    ProtocolRoutingEmitter: Runtime-checkable protocol for emission backends

Operation Mapping (from node contract io_operations):
    - emit_routing_decision operation -> ProtocolRoutingEmitter.emit_routing_decision()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Implement emit_routing_decision for event emission
"""

from .protocol_routing_emitter import ProtocolRoutingEmitter

__all__ = [
    "ProtocolRoutingEmitter",
]
