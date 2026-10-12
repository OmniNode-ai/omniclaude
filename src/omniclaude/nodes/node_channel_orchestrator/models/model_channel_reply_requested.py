# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Event model for onex.evt.omniclaw.channel-reply-requested.v1."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType


class ModelChannelReplyRequested(BaseModel):
    """A reply the orchestrator wants dispatched to the originating channel.

    The contract's ``published_events`` entry ``ChannelReplyRequested`` is
    matched to this class by its name minus the ``Model`` prefix, which is how
    the runtime picks the topic for an emitted model. The fields are declared
    here, not inherited from the orchestrator output, so the event schema is
    its own and moves only when the event does. They are field-for-field the
    request model of the reply dispatcher that subscribes to the topic
    (``ModelChannelReply``), and a test pins that the dispatcher accepts the
    serialized event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    reply_text: str = Field(..., description="Generated reply text")

    channel_id: str = Field(
        ..., min_length=1, description="Platform-specific channel/room ID"
    )
    channel_type: EnumChannelType = Field(..., description="Messaging platform type")

    reply_to: str | None = Field(default=None, description="Message ID to reply to")
    thread_id: str | None = Field(default=None, description="Thread/conversation ID")

    correlation_id: UUID = Field(..., description="Correlation ID for tracing")
