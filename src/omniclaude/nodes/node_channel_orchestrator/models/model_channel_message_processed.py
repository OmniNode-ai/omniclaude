# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Event model for onex.evt.omniclaw.channel-message-processed.v1."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType


class ModelChannelMessageProcessed(BaseModel):
    """Observability record that the orchestrator processed one channel message.

    Published on an ``onex.evt.*`` topic, so it carries routing identifiers
    only: never the sender, the display name or the message text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    channel_id: str = Field(
        ..., min_length=1, description="Platform-specific channel/room ID"
    )
    channel_type: EnumChannelType = Field(..., description="Messaging platform type")
    message_id: str | None = Field(
        default=None, description="Platform-specific ID of the processed message"
    )
    received_at: datetime = Field(
        ..., description="When the adapter received the message (from the envelope)"
    )
    reply_requested: bool = Field(
        ..., description="Whether a reply-requested event was emitted for it"
    )
    correlation_id: UUID = Field(..., description="Correlation ID for tracing")
