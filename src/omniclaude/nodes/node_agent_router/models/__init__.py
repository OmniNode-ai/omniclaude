# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Models for the NodeAgentRouter node.

Compute node models — routing request/response wrapping AgentRouter.
All models are frozen and inert (no logic methods).

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to
    import them, that is the signal to promote to omnibase_core.
"""

from .model_agent_recommendation import ModelAgentRecommendation
from .model_agent_router_request import ModelAgentRouterRequest
from .model_agent_router_result import ModelAgentRouterResult

__all__ = [
    "ModelAgentRecommendation",
    "ModelAgentRouterRequest",
    "ModelAgentRouterResult",
]
