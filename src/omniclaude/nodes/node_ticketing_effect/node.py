# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Ticketing Effect - 100% contract-driven.

This module provides the NodeTicketingEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: ticketing.base

NodeTicketingEffect is the abstract base for ticketing effect nodes. It defines
the common interface for any ticketing system (Linear, GitHub Issues, Jira, etc.).

Concrete implementations:
    - NodeLinearEffect: Linear-specific ticketing via ProtocolLinearTicketing

The node exposes abstract ticketing operations:
- ticket_get: Fetch a ticket by identifier
- ticket_update_status: Update ticket workflow status
- ticket_add_comment: Append a comment to a ticket

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolTicketingBase). Concrete ticketing backends implement this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeTicketingEffect(NodeEffect):
    """Abstract base effect node for ticketing system operations.

    Capability: ticketing.base

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.

    Concrete subclasses (NodeLinearEffect) implement vendor-specific behavior.
    This base node is used when the caller is vendor-agnostic.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the ticketing base effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeTicketingEffect"]
