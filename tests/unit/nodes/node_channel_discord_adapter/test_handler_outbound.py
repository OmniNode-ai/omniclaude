# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Discord outbound handler.

Tests that ModelChannelReply instances are correctly sent via
the Discord API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

discord = pytest.importorskip("discord", reason="discord.py not installed")

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_discord_adapter.handlers.handler_outbound import (
    send_discord_reply,
)
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)


def _make_reply(
    *,
    reply_text: str = "Hi there",
    channel_id: str = "456",
    reply_to: str | None = None,
    thread_id: str | None = None,
) -> ModelChannelReply:
    return ModelChannelReply(
        reply_text=reply_text,
        channel_id=channel_id,
        channel_type=EnumChannelType.DISCORD,
        reply_to=reply_to,
        thread_id=thread_id,
        correlation_id=uuid4(),
    )


@pytest.mark.unit
class TestSendDiscordReply:
    """Tests for send_discord_reply."""

    @pytest.mark.asyncio
    async def test_sends_plain_message(self) -> None:
        reply = _make_reply(reply_text="Hello!")
        client = MagicMock(spec=discord.Client)
        channel = AsyncMock(spec=discord.TextChannel)
        client.get_channel.return_value = channel

        await send_discord_reply(reply, client=client)

        client.get_channel.assert_called_once_with(456)
        channel.send.assert_awaited_once_with("Hello!")

    @pytest.mark.asyncio
    async def test_replies_to_original_message(self) -> None:
        reply = _make_reply(reply_text="Got it", reply_to="111")
        client = MagicMock(spec=discord.Client)
        channel = AsyncMock(spec=discord.TextChannel)
        client.get_channel.return_value = channel
        original_msg = AsyncMock()
        channel.fetch_message.return_value = original_msg

        await send_discord_reply(reply, client=client)

        channel.fetch_message.assert_awaited_once_with(111)
        original_msg.reply.assert_awaited_once_with("Got it")

    @pytest.mark.asyncio
    async def test_falls_back_when_original_not_found(self) -> None:
        reply = _make_reply(reply_text="Fallback", reply_to="999")
        client = MagicMock(spec=discord.Client)
        channel = AsyncMock(spec=discord.TextChannel)
        client.get_channel.return_value = channel
        channel.fetch_message.side_effect = discord.NotFound(
            MagicMock(status=404), "Not found"
        )

        await send_discord_reply(reply, client=client)

        channel.send.assert_awaited_once_with("Fallback")

    @pytest.mark.asyncio
    async def test_fetches_channel_when_not_cached(self) -> None:
        reply = _make_reply(channel_id="789")
        client = MagicMock(spec=discord.Client)
        client.get_channel.return_value = None
        channel = AsyncMock(spec=discord.TextChannel)
        client.fetch_channel = AsyncMock(return_value=channel)

        await send_discord_reply(reply, client=client)

        client.fetch_channel.assert_awaited_once_with(789)
        channel.send.assert_awaited_once_with("Hi there")

    @pytest.mark.asyncio
    async def test_skips_non_messageable_channel(self) -> None:
        reply = _make_reply()
        client = MagicMock(spec=discord.Client)
        # Return a non-messageable object
        non_messageable = MagicMock()
        # Ensure isinstance check for Messageable fails
        non_messageable.__class__ = type("CategoryChannel", (), {})
        client.get_channel.return_value = non_messageable

        # Should not raise
        await send_discord_reply(reply, client=client)
