# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeAgentRoutingCompute node.

This package defines the protocol interface for agent routing compute backends.

Exported:
    ProtocolAgentRouting: Runtime-checkable protocol for routing compute backends

Operation Mapping (from node contract io_operations):
    - compute_routing operation -> ProtocolAgentRouting.compute_routing()

Backend implementations must:
    1. Evaluate user prompts against agent registries
    2. Score each agent with confidence breakdowns
    3. Return routing decisions with full candidate lists
"""

from .protocol_agent_routing import ProtocolAgentRouting

__all__ = [
    "ProtocolAgentRouting",
]
