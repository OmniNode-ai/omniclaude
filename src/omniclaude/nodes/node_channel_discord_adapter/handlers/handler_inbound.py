# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Discord inbound handler.

Converts discord.py Message objects into ModelChannelEnvelope instances
for publishing to the OmniClaw event bus.

Related:
    - OMN-7189: Discord channel adapter contract package
"""

from __future__ import annotations

import logging
from datetime import UTC

import discord  # type: ignore[import-untyped]

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


def message_to_envelope(message: discord.Message) -> ModelChannelEnvelope | None:
    """Convert a Discord message to a normalized channel envelope.

    Args:
        message: The discord.py Message object.

    Returns:
        ModelChannelEnvelope if the message should be processed, None if
        the message should be skipped (e.g. bot messages).
    """
    if message.author.bot:
        return None

    # Determine thread context
    thread_id: str | None = None
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)

    # Use UTC-aware timestamp; discord.py provides naive UTC datetimes
    timestamp = message.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    return ModelChannelEnvelope(
        channel_id=str(message.channel.id),
        channel_type=EnumChannelType.DISCORD,
        sender_id=str(message.author.id),
        sender_display_name=message.author.display_name,
        message_text=message.content,
        message_id=str(message.id),
        thread_id=thread_id,
        timestamp=timestamp,
    )
