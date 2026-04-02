# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Discord outbound handler.

Sends reply messages to Discord channels via the bot API.

Related:
    - OMN-7189: Discord channel adapter contract package
"""

from __future__ import annotations

import logging

import discord  # type: ignore[import-untyped]

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


async def send_discord_reply(
    reply: ModelChannelReply,
    *,
    client: discord.Client,
) -> None:
    """Send a reply to a Discord channel.

    If ``reply.reply_to`` is set, fetches the original message and uses
    Discord's reply feature. Otherwise sends a plain message to the channel.

    Args:
        reply: The channel reply to send.
        client: An authenticated discord.py Client instance.
    """
    channel = client.get_channel(int(reply.channel_id))
    if channel is None:
        channel = await client.fetch_channel(int(reply.channel_id))

    if not isinstance(channel, discord.abc.Messageable):
        logger.error(
            "Channel %s is not messageable, correlation_id=%s",
            reply.channel_id,
            reply.correlation_id,
        )
        return

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
