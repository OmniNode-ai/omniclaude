# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeLinearEffect - Contract-driven effect node for Linear ticketing operations.

This package provides the NodeLinearEffect node for all Linear API operations
with pluggable backends.

Capability: linear.ticketing

INVARIANT: This node is the only place Linear API calls (LinearClient,
linear_client) are permitted.

Exported Components:
    Node:
        NodeLinearEffect - The effect node class (minimal shell)

    Models:
        ModelLinearRequest - Input model for Linear operations
        ModelLinearResult - Output model for Linear operations

    Protocols:
        ProtocolLinearTicketing - Interface for Linear backends
"""

from .models import ModelLinearRequest, ModelLinearResult
from .node import NodeLinearEffect
from .protocols import ProtocolLinearTicketing

__all__ = [
    # Node
    "NodeLinearEffect",
    # Models
    "ModelLinearRequest",
    "ModelLinearResult",
    # Protocols
    "ProtocolLinearTicketing",
]
