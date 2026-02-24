# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeTicketingEffect node.

This package defines the vendor-agnostic ticketing protocol interface.

Exported:
    ProtocolTicketingBase: Runtime-checkable protocol for ticketing backends

Operation Mapping (from node contract io_operations):
    - ticket_get operation -> ProtocolTicketingBase.ticket_get()
    - ticket_update_status operation -> ProtocolTicketingBase.ticket_update_status()
    - ticket_add_comment operation -> ProtocolTicketingBase.ticket_add_comment()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Keep vendor-specific API clients inside the implementation
"""

from .protocol_ticketing_base import ProtocolTicketingBase

__all__ = [
    "ProtocolTicketingBase",
]
