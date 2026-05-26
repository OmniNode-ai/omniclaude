# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Handlers for the NodeAgentRouter node.

This package contains the default handler implementation that satisfies
ProtocolAgentRouter by wrapping AgentRouter from lib/core/agent_router.py.

Exported:
    HandlerAgentRouter: Default routing handler wrapping AgentRouter.
"""

from .handler_agent_router import HandlerAgentRouter

__all__ = [
    "HandlerAgentRouter",
]
