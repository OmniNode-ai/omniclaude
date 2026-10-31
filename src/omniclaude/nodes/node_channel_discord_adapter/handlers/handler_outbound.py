# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Discord outbound handler.

Sends reply messages to Discord channels via the bot API.

Related:
    - OMN-7189: Discord channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import logging

import discord  # type: ignore[import-not-found]  # Why: discord.py is an optional dependency

from omniclaude.nodes.node_channel_discord_adapter.models.model_discord_outbound_result import (
    ModelDiscordOutboundResult,
)
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


class HandlerDiscordOutbound:
    """Send a channel reply through an authenticated Discord client."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client

    async def handle(self, request: ModelChannelReply) -> ModelDiscordOutboundResult:
        """Send a reply to a Discord channel.

        If ``request.reply_to`` is set, fetches the original message and uses
        Discord's reply feature. Otherwise sends a plain message to the channel.

        Returns:
            A result whose ``delivered`` is False when the channel cannot take
            messages.
        """
        reply = request
        channel = self._client.get_channel(int(reply.channel_id))
        if channel is None:
            channel = await self._client.fetch_channel(int(reply.channel_id))

        if not isinstance(channel, discord.abc.Messageable):
            logger.error(
                "Channel %s is not messageable, correlation_id=%s",
                reply.channel_id,
                reply.correlation_id,
            )
            return ModelDiscordOutboundResult(delivered=False)

        if reply.reply_to:
            try:
                message = await channel.fetch_message(int(reply.reply_to))
                await message.reply(reply.reply_text)
            except discord.NotFound:
                logger.warning(
                    "Original message %s not found, sending as plain message, "
                    "correlation_id=%s",
                    reply.reply_to,
                    reply.correlation_id,
                )
                await channel.send(reply.reply_text)
        else:
            await channel.send(reply.reply_text)
        return ModelDiscordOutboundResult(delivered=True)
