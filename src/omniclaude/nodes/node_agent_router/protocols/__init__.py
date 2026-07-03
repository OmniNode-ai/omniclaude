# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Protocols for the NodeAgentRouter node.

This package contains the ProtocolAgentRouter interface that all
routing backends must implement.

Exported:
    ProtocolAgentRouter: Protocol for agent router compute backends.
"""

from .protocol_agent_router import ProtocolAgentRouter

__all__ = [
    "ProtocolAgentRouter",
]
