# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeTicketingEffect - Abstract base effect node for ticketing system operations.

This package provides the NodeTicketingEffect node as a vendor-agnostic base
for any ticketing backend (Linear, GitHub Issues, Jira, etc.).

Capability: ticketing.base

Concrete implementations:
    - NodeLinearEffect: Linear-specific ticketing

Exported Components:
    Node:
        NodeTicketingEffect - The abstract base effect node class

    Models:
        ModelTicketingRequest - Input model for ticketing operations
        ModelTicketingResult - Output model for ticketing operations

    Protocols:
        ProtocolTicketingBase - Vendor-agnostic ticketing interface
"""

from .models import ModelTicketingRequest, ModelTicketingResult
from .node import NodeTicketingEffect
from .protocols import ProtocolTicketingBase

__all__ = [
    # Node
    "NodeTicketingEffect",
    # Models
    "ModelTicketingRequest",
    "ModelTicketingResult",
    # Protocols
    "ProtocolTicketingBase",
]
