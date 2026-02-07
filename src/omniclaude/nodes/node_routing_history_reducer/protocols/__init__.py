# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeRoutingHistoryReducer node.

This package defines the protocol interface for routing history storage backends.

Exported:
    ProtocolHistoryStore: Runtime-checkable protocol for history storage backends

Operation Mapping (from node contract io_operations):
    - record_routing_decision operation -> ProtocolHistoryStore.record_routing_decision()
    - query_routing_stats operation -> ProtocolHistoryStore.query_routing_stats()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Implement record_routing_decision with idempotent behavior
    3. Implement query_routing_stats with optional agent_name filtering
"""

from .protocol_history_store import ProtocolHistoryStore

__all__ = [
    "ProtocolHistoryStore",
]
