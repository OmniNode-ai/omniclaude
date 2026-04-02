# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Normalized channel message envelope for OmniClaw."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType  # noqa: TC002


class ModelChannelEnvelope(BaseModel):
    """Normalized inbound message from any channel adapter.

    Represents a single message received from a supported messaging platform,
    normalized to a common schema before processing by the OmniClaw pipeline.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    # Channel routing
    channel_id: str = Field(..., min_length=1, description="Platform-specific channel/room ID")
    channel_type: EnumChannelType = Field(..., description="Messaging platform type")

    # Sender (kept for business logic; must not be logged per PII rules)
    # string-id-ok: sender_id is a platform-specific user identifier
    sender_id: str = Field(..., description="Platform-specific sender identifier")
    # string-id-ok: sender_display_name is a platform-provided display name
    sender_display_name: str | None = Field(default=None, description="Human-readable sender name")

    # Message content
    message_text: str = Field(..., description="Raw message text from the sender")
    # string-id-ok: message_id is a platform-specific message identifier
    message_id: str | None = Field(default=None, description="Platform-specific message ID")

    # Thread context
    # string-id-ok: thread_id is a platform-specific thread identifier
    thread_id: str | None = Field(default=None, description="Thread/conversation ID if applicable")

    # Timing
    timestamp: datetime = Field(..., description="When the message was received")

    # Tracing
    correlation_id: UUID = Field(
        default_factory=uuid4, description="Correlation ID for end-to-end tracing"
    )
