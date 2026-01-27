# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodePatternPersistenceEffect node.

This package defines the protocol interface for learned pattern persistence backends.

Exported:
    ProtocolPatternPersistence: Runtime-checkable protocol for persistence backends

Operation Mapping (from node contract io_operations):
    - query_patterns operation -> ProtocolPatternPersistence.query_patterns()
    - upsert_pattern operation -> ProtocolPatternPersistence.upsert_pattern()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Implement query_patterns with defined execution order
    3. Implement upsert_pattern with idempotent behavior (ON CONFLICT UPDATE)
"""

from .protocol_pattern_persistence import ProtocolPatternPersistence

__all__ = [
    "ProtocolPatternPersistence",
]
