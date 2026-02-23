# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for Claude Code session backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_claude_code_session_effect.models import (
    ModelClaudeCodeSessionRequest,
)
from omniclaude.nodes.shared.models.model_skill_result import ModelSkillResult


@runtime_checkable
class ProtocolClaudeCodeSession(Protocol):
    """Runtime-checkable protocol for Claude Code session backends.

    All session backend implementations must implement this protocol.
    All operations emit ModelSkillResult envelopes.

    Operation mapping (from node contract io_operations):
        - session_start operation -> session_start()
        - session_query operation -> session_query()
        - session_end operation -> session_end()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'subprocess')."""
        ...

    async def session_start(
        self, request: ModelClaudeCodeSessionRequest
    ) -> ModelSkillResult:
        """Start a new Claude Code session.

        Args:
            request: Session request with working_directory populated.

        Returns:
            ModelSkillResult with session_id in output field on success.
        """
        ...

    async def session_query(
        self, request: ModelClaudeCodeSessionRequest
    ) -> ModelSkillResult:
        """Submit a prompt to an active Claude Code session.

        Args:
            request: Session request with session_id and prompt populated.

        Returns:
            ModelSkillResult with Claude Code response in output field.
        """
        ...

    async def session_end(
        self, request: ModelClaudeCodeSessionRequest
    ) -> ModelSkillResult:
        """Terminate a Claude Code session.

        Args:
            request: Session request with session_id populated.

        Returns:
            ModelSkillResult confirming session termination.
        """
        ...


__all__ = ["ProtocolClaudeCodeSession"]
