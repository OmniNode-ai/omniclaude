# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Slack inbound handler.

Converts Slack Events API message payloads into ModelChannelEnvelope
instances for publishing to the OmniClaw event bus.

Related:
    - OMN-7190: Slack channel adapter contract package
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


class ModelSlackMessageEvent(BaseModel):
    """Typed representation of a Slack Events API message payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str = Field(..., description="Slack channel ID")
    ts: str = Field(..., description="Message timestamp (Slack message ID)")
    user: str = Field(default="", description="Slack user ID")
    text: str = Field(default="", description="Message text")
    thread_ts: str | None = Field(default=None, description="Thread timestamp")
    subtype: str | None = Field(default=None, description="Message subtype")
    bot_id: str | None = Field(default=None, description="Bot ID if from a bot")


def event_to_envelope(
    event: ModelSlackMessageEvent | dict[str, str],
) -> ModelChannelEnvelope | None:
    """Convert a Slack message event to a normalized channel envelope.

    Args:
        event: Slack Events API ``message`` event payload, either as a
            ``ModelSlackMessageEvent`` or a raw dict (auto-parsed).

    Returns:
        ModelChannelEnvelope if the message should be processed, None if
        the message should be skipped (e.g. bot messages).
    """
    if isinstance(event, dict):
        event = ModelSlackMessageEvent.model_validate(event)

    # Filter bot messages: Slack uses both patterns
    if event.subtype == "bot_message" or event.bot_id is not None:
        return None

    # Slack Events API does not include display name in message events;
    # resolving via users.info is deferred to avoid rate limiting.
    timestamp = datetime.fromtimestamp(float(event.ts), tz=UTC)

    return ModelChannelEnvelope(
        channel_id=event.channel,
        channel_type=EnumChannelType.SLACK,
        sender_id=event.user,
        sender_display_name=None,
        message_text=event.text,
        message_id=event.ts,
        thread_id=event.thread_ts,
        timestamp=timestamp,
    )
