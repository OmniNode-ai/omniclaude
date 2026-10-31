# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Discord inbound handler.

Converts discord.py Message objects into ModelChannelEnvelope instances
for publishing to the OmniClaw event bus.

Related:
    - OMN-7189: Discord channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import logging
from datetime import UTC

import discord  # type: ignore[import-not-found]  # Why: discord.py is an optional dependency
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_discord_adapter.models.model_discord_inbound_result import (
    ModelDiscordInboundResult,
)
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


class ModelDiscordInboundRequest(BaseModel):
    """One discord.py Message to normalize into a channel envelope."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    message: discord.Message = Field(..., description="The discord.py Message object")


class HandlerDiscordInbound:
    """Convert a Discord message to a normalized channel envelope."""

    def handle(self, request: ModelDiscordInboundRequest) -> ModelDiscordInboundResult:
        """Convert the request's Discord message.

        Returns:
            A result whose envelope is set if the message should be processed,
            and None if the message should be skipped (e.g. bot messages).
        """
        message = request.message
        if message.author.bot:
            return ModelDiscordInboundResult(envelope=None)

        # Determine thread context
        thread_id: str | None = None
        if isinstance(message.channel, discord.Thread):
            thread_id = str(message.channel.id)

        # Use UTC-aware timestamp; discord.py provides naive UTC datetimes
        timestamp = message.created_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)

        return ModelDiscordInboundResult(
            envelope=ModelChannelEnvelope(
                channel_id=str(message.channel.id),
                channel_type=EnumChannelType.DISCORD,
                sender_id=str(message.author.id),
                sender_display_name=message.author.display_name,
                message_text=message.content,
                message_id=str(message.id),
                thread_id=thread_id,
                timestamp=timestamp,
            )
        )
