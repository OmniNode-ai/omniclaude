# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeLinearEffect node.

This package defines the protocol interface for Linear ticketing backends.

Exported:
    ProtocolLinearTicketing: Runtime-checkable protocol for Linear backends

Operation Mapping (from node contract io_operations):
    - ticket_get operation -> ProtocolLinearTicketing.ticket_get()
    - ticket_update_status operation -> ProtocolLinearTicketing.ticket_update_status()
    - ticket_add_comment operation -> ProtocolLinearTicketing.ticket_add_comment()
    - ticket_create operation -> ProtocolLinearTicketing.ticket_create()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Keep LinearClient/linear_client imports inside the implementation
    3. Never expose Linear API keys or tokens in results
"""

from .protocol_linear_ticketing import ProtocolLinearTicketing

__all__ = [
    "ProtocolLinearTicketing",
]
