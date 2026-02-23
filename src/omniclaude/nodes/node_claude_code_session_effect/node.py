# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Node Claude Code Session Effect - 100% contract-driven.

This module provides the NodeClaudeCodeSessionEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: claude_code.session

The node exposes Claude Code session management:
- session_start: Start a new Claude Code session
- session_query: Submit a query to an active session
- session_end: Terminate a Claude Code session

All operations emit ModelSkillResult envelopes as output.

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolClaudeCodeSession). The actual session backend implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeClaudeCodeSessionEffect(NodeEffect):
    """Effect node for Claude Code session management.

    Capability: claude_code.session

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    Emits ModelSkillResult envelope on all operations.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the Claude Code session effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeClaudeCodeSessionEffect"]
