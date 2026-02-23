# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for vendor-agnostic ticketing backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_ticketing_effect.models import (
    ModelTicketingRequest,
    ModelTicketingResult,
)


@runtime_checkable
class ProtocolTicketingBase(Protocol):
    """Runtime-checkable protocol for vendor-agnostic ticketing backends.

    All ticketing backend implementations must implement this protocol.
    Vendor-specific clients must live inside the implementation, not in callers.

    Concrete implementations:
        - LinearTicketingHandler: handler_key='linear', implements via Linear API

    Operation mapping (from node contract io_operations):
        - ticket_get operation -> ticket_get()
        - ticket_update_status operation -> ticket_update_status()
        - ticket_add_comment operation -> ticket_add_comment()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'linear')."""
        ...

    async def ticket_get(self, request: ModelTicketingRequest) -> ModelTicketingResult:
        """Fetch a ticket by identifier.

        Args:
            request: Ticketing request with ticket_id populated.

        Returns:
            ModelTicketingResult with ticket_id, ticket_url, and output populated.
        """
        ...

    async def ticket_update_status(
        self, request: ModelTicketingRequest
    ) -> ModelTicketingResult:
        """Update the workflow status of a ticket.

        Args:
            request: Ticketing request with ticket_id and status populated.

        Returns:
            ModelTicketingResult confirming the status update.
        """
        ...

    async def ticket_add_comment(
        self, request: ModelTicketingRequest
    ) -> ModelTicketingResult:
        """Append a comment to a ticket.

        Args:
            request: Ticketing request with ticket_id and comment_body populated.

        Returns:
            ModelTicketingResult confirming the comment was added.
        """
        ...


__all__ = ["ProtocolTicketingBase"]
