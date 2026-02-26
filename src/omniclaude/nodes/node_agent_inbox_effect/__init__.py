# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeAgentInboxEffect - Contract-driven effect node for inter-agent messaging.

This package provides the NodeAgentInboxEffect node for delivering
inter-agent messages with dual delivery (EVENT_BUS+ and STANDALONE).

Capability: agent.inbox

Exported Components:
    Node:
        NodeAgentInboxEffect - The effect node class (minimal shell)

    Models:
        ModelInboxMessage - Versioned message envelope
        ModelMessageTrace - Trace context embedded in messages
        ModelInboxDeliveryResult - Delivery operation result

    Protocols:
        ProtocolAgentInbox - Interface for inbox backends

    Handlers:
        HandlerStandaloneInbox - File-based inbox (STANDALONE tier)
        HandlerKafkaInbox - Kafka-based inbox (EVENT_BUS+ tier)

Example Usage:
    ```python
    from omniclaude.nodes.node_agent_inbox_effect import (
        NodeAgentInboxEffect,
        ModelInboxMessage,
        HandlerStandaloneInbox,
    )

    # Create standalone handler
    handler = HandlerStandaloneInbox()

    # Send a directed message
    result = await handler.send_message(message)
    ```
"""

from .handler_kafka_inbox import HandlerKafkaInbox
from .handler_standalone_inbox import HandlerStandaloneInbox
from .models import (
    ModelInboxDeliveryResult,
    ModelInboxMessage,
    ModelMessageTrace,
)
from .node import NodeAgentInboxEffect
from .protocols import ProtocolAgentInbox

__all__ = [
    # Node
    "NodeAgentInboxEffect",
    # Models
    "ModelInboxDeliveryResult",
    "ModelInboxMessage",
    "ModelMessageTrace",
    # Protocols
    "ProtocolAgentInbox",
    # Handlers
    "HandlerKafkaInbox",
    "HandlerStandaloneInbox",
]
