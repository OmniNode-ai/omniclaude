# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the GitHub PR watcher effect node.

InboxRouteResult: result of routing a PR status event to agent inboxes.
WatchRegistration: request to register/unregister an agent watch.
AgentInboxMessage: message envelope for per-agent inbox topics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

__all__ = [
    "AgentInboxMessage",
    "InboxRouteResult",
    "WatchRegistration",
]


class InboxRouteResult(BaseModel):
    """Result of routing a PR status event to agent inboxes."""

    agents_notified: list[str] = Field(
        default_factory=list,
        description="Agent IDs that received the event",
    )
    inbox_topics: list[str] = Field(
        default_factory=list,
        description="Kafka topics the event was published to",
    )
    event_dedupe_key: str = Field(..., description="Dedupe key of the routed event")
    routed_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Timestamp when routing completed",
    )


class WatchRegistration(BaseModel):
    """Request to register or unregister an agent watch."""

    agent_id: str = Field(..., description="Agent identifier")
    repo: str = Field(..., description="Full repo slug")
    pr_number: int = Field(..., description="PR number to watch")


class AgentInboxMessage(BaseModel):
    """Message envelope for per-agent inbox topics.

    Topic: ``onex.evt.omniclaude.agent-inbox.{agent_id}.v1``
    Partition key: ``agent_id``
    Consumer group: ``omniclaude.inbox.{agent_id}``

    Uses Phase 3 message envelope fields.
    """

    # Phase 3 envelope fields
    schema_version: str = Field(
        default="1.0.0", description="Schema version for inbox messages"
    )
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique message identifier",
    )
    emitted_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of emission",
    )
    trace: dict[str, str] = Field(
        default_factory=dict,
        description="Trace context (correlation_id, parent_id, etc.)",
    )

    # Routing metadata
    agent_id: str = Field(..., description="Target agent identifier")
    event_type: str = Field(
        ..., description="Type of the original event, e.g. 'pr-status'"
    )
    source_topic: str = Field(
        ..., description="Topic the original event was consumed from"
    )

    # Event payload (the PR status event data)
    payload: dict[str, Any] = Field(..., description="Original event payload")

    @classmethod
    def from_pr_status(
        cls,
        agent_id: str,
        pr_status_payload: dict[str, Any],
        *,
        trace: dict[str, str] | None = None,
    ) -> AgentInboxMessage:
        """Create an inbox message from a PR status event payload.

        Args:
            agent_id: Target agent identifier.
            pr_status_payload: The PR status event dict.
            trace: Optional trace context.

        Returns:
            AgentInboxMessage ready for Kafka publication.
        """
        return cls(
            agent_id=agent_id,
            event_type="pr-status",
            source_topic="onex.evt.omniclaude.github-pr-status.v1",
            payload=pr_status_payload,
            trace=trace or {},
        )
