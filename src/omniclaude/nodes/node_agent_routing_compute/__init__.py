# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeAgentRoutingCompute - Contract-driven compute node for agent routing.

This package provides the NodeAgentRoutingCompute node for evaluating user
prompts against agent registries and producing routing decisions with
confidence scoring.

Capability: agent.routing.compute

Exported Components:
    Node:
        NodeAgentRoutingCompute - The compute node class (minimal shell)

    Models:
        ModelAgentDefinition - Agent definition for the registry
        ModelConfidenceBreakdown - Detailed confidence score breakdown
        ModelRoutingCandidate - A single routing candidate with scores
        ModelRoutingRequest - Input to the routing compute node
        ModelRoutingResult - Output from the routing compute node

    Protocols:
        ProtocolAgentRouting - Interface for routing compute backends

Example Usage:
    ```python
    from omniclaude.nodes.node_agent_routing_compute import (
        NodeAgentRoutingCompute,
        ModelRoutingRequest,
        ProtocolAgentRouting,
    )

    # Resolve handler via container
    handler = await container.get_service_async(ProtocolAgentRouting)

    # Compute routing
    request = ModelRoutingRequest(
        prompt="Design a REST API for user management",
        correlation_id=uuid4(),
        agent_registry=agents,
    )
    result = await handler.compute_routing(request)
    ```
"""

from .models import (
    ModelAgentDefinition,
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
    ModelRoutingResult,
)
from .node import NodeAgentRoutingCompute
from .protocols import ProtocolAgentRouting

__all__ = [
    # Node
    "NodeAgentRoutingCompute",
    # Models
    "ModelAgentDefinition",
    "ModelConfidenceBreakdown",
    "ModelRoutingCandidate",
    "ModelRoutingRequest",
    "ModelRoutingResult",
    # Protocols
    "ProtocolAgentRouting",
]
