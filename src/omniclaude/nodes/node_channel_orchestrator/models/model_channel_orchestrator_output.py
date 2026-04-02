# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Output model for channel orchestrator node."""

from __future__ import annotations

from uuid import UUID

from omnibase_core.enums.enum_channel_type import EnumChannelType  # noqa: TC002
from pydantic import BaseModel, ConfigDict, Field


class ModelChannelOrchestratorOutput(BaseModel):
    """Output from the channel orchestrator.

    Contains the reply text and routing metadata needed for the reply
    dispatcher to fan out to the correct channel adapter.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    # Reply content
    reply_text: str = Field(..., description="Generated reply text")

    # Routing metadata (copied from input envelope for fan-out)
    # string-id-ok: channel_id is a platform-specific identifier
    channel_id: str = Field(
        ..., min_length=1, description="Platform-specific channel/room ID"
    )
    channel_type: EnumChannelType = Field(..., description="Messaging platform type")

    # Thread context
    # string-id-ok: reply_to is a platform-specific message identifier
    reply_to: str | None = Field(default=None, description="Message ID to reply to")
    # string-id-ok: thread_id is a platform-specific thread identifier
    thread_id: str | None = Field(default=None, description="Thread/conversation ID")

    # Tracing
    correlation_id: UUID = Field(..., description="Correlation ID from input envelope")
