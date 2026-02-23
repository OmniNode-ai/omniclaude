# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeClaudeCodeSessionEffect - Contract-driven effect node for Claude Code sessions.

This package provides the NodeClaudeCodeSessionEffect node for managing
Claude Code sessions with pluggable backends.

Capability: claude_code.session

All operations emit ModelSkillResult envelopes as output.

Exported Components:
    Node:
        NodeClaudeCodeSessionEffect - The effect node class (minimal shell)

    Models:
        ModelClaudeCodeSessionRequest - Input model for session operations

    Protocols:
        ProtocolClaudeCodeSession - Interface for session backends
"""

from .models import ModelClaudeCodeSessionRequest
from .node import NodeClaudeCodeSessionEffect
from .protocols import ProtocolClaudeCodeSession

__all__ = [
    # Node
    "NodeClaudeCodeSessionEffect",
    # Models
    "ModelClaudeCodeSessionRequest",
    # Protocols
    "ProtocolClaudeCodeSession",
]
