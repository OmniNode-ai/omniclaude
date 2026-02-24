# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Linear Effect - 100% contract-driven.

This module provides the NodeLinearEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: linear.ticketing

The node exposes Linear ticketing operations:
- ticket_get: Fetch a ticket by ID
- ticket_update_status: Update the status of a ticket
- ticket_add_comment: Add a comment to a ticket
- ticket_create: Create a new ticket

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolLinearTicketing). The actual Linear API backend implements this protocol.

INVARIANT: No direct Linear API calls (LinearClient, linear_client) are permitted
outside this effect node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeLinearEffect(NodeEffect):
    """Effect node for Linear ticketing operations.

    Capability: linear.ticketing

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.

    INVARIANT: This node is the only place Linear API calls are permitted.
    All LinearClient and linear_client imports must live in the handler implementation.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the Linear effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeLinearEffect"]
