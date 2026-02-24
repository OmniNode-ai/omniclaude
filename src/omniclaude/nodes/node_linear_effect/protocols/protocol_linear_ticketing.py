# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for Linear ticketing backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_linear_effect.models import (
    ModelLinearRequest,
    ModelLinearResult,
)


@runtime_checkable
class ProtocolLinearTicketing(Protocol):
    """Runtime-checkable protocol for Linear ticketing backends.

    All Linear backend implementations must implement this protocol.
    LinearClient and linear_client imports must live inside implementations;
    they are not permitted in any other node.

    Operation mapping (from node contract io_operations):
        - ticket_get operation -> ticket_get()
        - ticket_update_status operation -> ticket_update_status()
        - ticket_add_comment operation -> ticket_add_comment()
        - ticket_create operation -> ticket_create()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'linear_api')."""
        ...

    async def ticket_get(self, request: ModelLinearRequest) -> ModelLinearResult:
        """Fetch a Linear ticket by identifier.

        Args:
            request: Linear request with ticket_id populated.

        Returns:
            ModelLinearResult with ticket_id, ticket_url, and output populated.
        """
        ...

    async def ticket_update_status(
        self, request: ModelLinearRequest
    ) -> ModelLinearResult:
        """Update the workflow status of a Linear ticket.

        Args:
            request: Linear request with ticket_id and status populated.

        Returns:
            ModelLinearResult confirming the status update.
        """
        ...

    async def ticket_add_comment(
        self, request: ModelLinearRequest
    ) -> ModelLinearResult:
        """Add a comment to a Linear ticket.

        Args:
            request: Linear request with ticket_id and comment_body populated.

        Returns:
            ModelLinearResult confirming the comment was added.
        """
        ...

    async def ticket_create(self, request: ModelLinearRequest) -> ModelLinearResult:
        """Create a new Linear ticket.

        Args:
            request: Linear request with title, description, and team_id populated.

        Returns:
            ModelLinearResult with ticket_id and ticket_url populated on success.
        """
        ...


__all__ = ["ProtocolLinearTicketing"]
