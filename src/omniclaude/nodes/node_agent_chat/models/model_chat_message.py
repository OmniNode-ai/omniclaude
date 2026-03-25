# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Agent chat message model — the typed domain model for broadcast chat.

Model ownership: PRIVATE to omniclaude.

This is deliberately NOT ModelInboxMessage (which is a transport envelope with
untyped payload). ModelAgentChatMessage is a fully typed domain model for the
agent chat broadcast system.

Related tickets:
    - OMN-3972: Agentic Chat Over Kafka MVP
    - OMN-6507: Contract models
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from omniclaude.nodes.node_agent_chat.enums.enum_chat_channel import EnumChatChannel
from omniclaude.nodes.node_agent_chat.enums.enum_chat_message_type import (
    EnumChatMessageType,
)
from omniclaude.nodes.node_agent_chat.enums.enum_chat_severity import EnumChatSeverity


class ModelAgentChatMessage(BaseModel):
    """Typed domain model for agent chat broadcast messages.

    Every field is validated and versioned. Messages are persisted to both
    a local JSONL file store and the Kafka event bus for cross-terminal
    delivery.

    Attributes:
        schema_version: Wire format version for forward compatibility.
        message_id: Unique identifier for this message (UUID v4).
        emitted_at: Timezone-aware timestamp of message production.
        session_id: Claude Code session that produced this message.
        agent_id: Logical agent identity (e.g., "epic-worker-1", "ci-watcher").
        channel: Logical broadcast channel for routing and filtering.
        message_type: Semantic classification of this message.
        severity: Visual and filtering priority level.
        body: Human-readable message text (the actual content).
        epic_id: Optional epic scope — set when channel is EPIC.
        correlation_id: Optional end-to-end correlation ID for tracing.
        ticket_id: Optional Linear ticket ID for context.
        metadata: Optional structured metadata for downstream consumers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    schema_version: str = Field(
        default="1",
        description="Wire format version for forward compatibility",
    )
    message_id: UUID = Field(
        default_factory=uuid4,
        description="Unique identifier for this message",
    )
    emitted_at: datetime = Field(
        ...,
        description="Timezone-aware timestamp of message production",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        description="Claude Code session that produced this message",
    )
    agent_id: str = Field(
        ...,
        min_length=1,
        description="Logical agent identity (e.g., epic-worker-1, ci-watcher)",
    )
    channel: EnumChatChannel = Field(
        default=EnumChatChannel.BROADCAST,
        description="Logical broadcast channel for routing and filtering",
    )
    message_type: EnumChatMessageType = Field(
        ...,
        description="Semantic classification of this message",
    )
    severity: EnumChatSeverity = Field(
        default=EnumChatSeverity.INFO,
        description="Visual and filtering priority level",
    )
    body: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="Human-readable message text",
    )
    epic_id: str | None = Field(
        default=None,
        description="Optional epic scope (set when channel is EPIC)",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Optional end-to-end correlation ID for tracing",
    )
    ticket_id: str | None = Field(
        default=None,
        description="Optional Linear ticket ID for context",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional structured metadata for downstream consumers",
    )

    @field_validator("emitted_at")
    @classmethod
    def _require_timezone_aware(cls, v: datetime) -> datetime:
        """Reject naive datetimes to enforce the explicit-timestamp invariant."""
        if v.tzinfo is None:
            raise ValueError("emitted_at must be timezone-aware (got naive datetime)")
        return v


__all__ = ["ModelAgentChatMessage"]
