# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Agent Inbox Effect - 100% contract-driven.

This module provides the NodeAgentInboxEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: agent.inbox

The node exposes three operations:
- send_message: Deliver a message to a directed agent inbox or epic broadcast
- receive_messages: Read pending messages from an agent inbox
- gc_inbox: Garbage collect expired messages from file-based inboxes

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolAgentInbox). The actual delivery backend (e.g., standalone, kafka)
implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeAgentInboxEffect(NodeEffect):
    """Effect node for inter-agent inbox message delivery.

    Capability: agent.inbox

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the agent inbox effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeAgentInboxEffect"]
