# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Channel reply model for the reply dispatcher."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType  # noqa: TC002


class ModelChannelReply(BaseModel):
    """Reply to be dispatched to a channel adapter.

    Produced by the channel orchestrator and consumed by the reply
    dispatcher for fan-out routing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    reply_text: str = Field(..., description="Generated reply text")

    # string-id-ok: channel_id is a platform-specific identifier
    channel_id: str = Field(
        ..., min_length=1, description="Platform-specific channel/room ID"
    )
    channel_type: EnumChannelType = Field(..., description="Messaging platform type")

    # string-id-ok: reply_to is a platform-specific message identifier
    reply_to: str | None = Field(default=None, description="Message ID to reply to")
    # string-id-ok: thread_id is a platform-specific thread identifier
    thread_id: str | None = Field(default=None, description="Thread/conversation ID")

    correlation_id: UUID = Field(..., description="Correlation ID for tracing")
