# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeAgentRouter - Contract-driven compute node for agent routing.

This package provides the NodeAgentRouter node, which wraps the legacy
AgentRouter class from lib/core/agent_router.py behind a proper ONEX
contract boundary.

Capability: agent.router

Exported Components:
    Node:
        NodeAgentRouter - The compute node class (minimal shell)

    Models:
        ModelAgentRecommendation - Typed representation of an agent recommendation
        ModelAgentRouterRequest - Input to the routing compute node
        ModelAgentRouterResult - Output from the routing compute node

    Protocols:
        ProtocolAgentRouter - Interface for routing compute backends

    Handlers:
        HandlerAgentRouter - Default handler wrapping AgentRouter

Example Usage:
    ```python
    from omniclaude.nodes.node_agent_router import (
        HandlerAgentRouter,
        ModelAgentRouterRequest,
    )

    handler = HandlerAgentRouter()
    request = ModelAgentRouterRequest(
        user_request="debug this performance issue",
        max_recommendations=3,
    )
    result = await handler.route(request)
    if result.routed:
        best = result.recommendations[0]
        print(f"Routed to {best.agent_name} (confidence={best.confidence:.2f})")
    ```
"""

from .handlers import HandlerAgentRouter
from .models import (
    ModelAgentRecommendation,
    ModelAgentRouterRequest,
    ModelAgentRouterResult,
)
from .node import NodeAgentRouter
from .protocols import ProtocolAgentRouter

__all__ = [
    # Node
    "NodeAgentRouter",
    # Models
    "ModelAgentRecommendation",
    "ModelAgentRouterRequest",
    "ModelAgentRouterResult",
    # Protocols
    "ProtocolAgentRouter",
    # Handlers
    "HandlerAgentRouter",
]
