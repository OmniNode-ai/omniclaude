# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for inter-agent inbox delivery backends.

Operation Mapping (from node contract io_operations):
    - send_message operation -> ProtocolAgentInbox.send_message()
    - receive_messages operation -> ProtocolAgentInbox.receive_messages()
    - gc_inbox operation -> ProtocolAgentInbox.gc_inbox()

Implementors must:
    1. Provide handler_key property identifying the backend (e.g., 'standalone', 'kafka')
    2. Implement send_message for delivering messages to agent inboxes
    3. Implement receive_messages for reading pending messages
    4. Implement gc_inbox for garbage collecting expired messages

Delivery Semantics:
    - Directed messages go to agent-specific inboxes (partition key = agent_id)
    - Broadcast messages go to epic-wide status topics
    - Dual delivery: EVENT_BUS+ (Kafka) and STANDALONE (file-based) may both be used
    - STANDALONE uses atomic writes (write to temp, rename) to prevent partial reads
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_agent_inbox_effect.models import (
    ModelInboxDeliveryResult,
    ModelInboxMessage,
)


@runtime_checkable
class ProtocolAgentInbox(Protocol):
    """Protocol for inter-agent inbox delivery backends.

    This protocol defines the interface for inbox backends that handle
    inter-agent message delivery. Implementations are responsible for:

    - Delivering directed messages to specific agent inboxes
    - Broadcasting messages to epic-wide status topics
    - Reading pending messages from agent inboxes
    - Garbage collecting expired messages

    Attributes:
        handler_key: Backend identifier used for routing (e.g., 'standalone', 'kafka')

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolAgentInbox)
        result = await handler.send_message(message)
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'standalone', 'kafka').

        This key is used for handler routing when multiple backends are
        registered. The node contract's handler_routing.backends configuration
        maps backend keys to handler implementations.
        """
        ...

    async def send_message(
        self,
        message: ModelInboxMessage,
    ) -> ModelInboxDeliveryResult:
        """Send a message to a directed agent inbox or epic broadcast topic.

        For directed messages (target_agent_id set):
            - EVENT_BUS+: Produces to onex.evt.omniclaude.agent-inbox.{agent_id}.v1
            - STANDALONE: Writes to ~/.claude/agent-inboxes/{agent_id}/{ts}_{id}.json

        For broadcast messages (target_epic_id set):
            - EVENT_BUS+: Produces to onex.evt.omniclaude.epic.{epic_id}.status.v1
            - STANDALONE: Writes to ~/.claude/agent-inboxes/_broadcast/{epic_id}/{ts}_{id}.json

        Args:
            message: The inbox message envelope to deliver.

        Returns:
            ModelInboxDeliveryResult with delivery status per tier.
            This method never raises; failures are reported in the result.
        """
        ...

    async def receive_messages(
        self,
        agent_id: str,
        since: datetime | None = None,
    ) -> list[ModelInboxMessage]:
        """Receive pending messages from an agent inbox.

        Reads messages from the inbox for the given agent, optionally
        filtered by timestamp. Messages are returned in timestamp order
        (oldest first).

        Args:
            agent_id: The agent whose inbox to read.
            since: Only return messages emitted after this timestamp.
                   If None, returns all available messages.

        Returns:
            List of ModelInboxMessage in timestamp order.
        """
        ...

    async def gc_inbox(
        self,
        ttl_hours: int = 24,
    ) -> int:
        """Garbage collect expired messages from file-based agent inboxes.

        Removes message files older than ttl_hours from all agent inboxes
        under ~/.claude/agent-inboxes/.

        Args:
            ttl_hours: Messages older than this many hours are removed.
                       Defaults to 24 hours.

        Returns:
            Number of message files removed.
        """
        ...
