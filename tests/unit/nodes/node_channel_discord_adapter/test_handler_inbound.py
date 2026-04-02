# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Discord inbound handler.

Tests that discord.Message objects are correctly converted to
ModelChannelEnvelope instances.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

discord = pytest.importorskip("discord", reason="discord.py not installed")

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_discord_adapter.handlers.handler_inbound import (
    message_to_envelope,
)


def _make_discord_message(
    *,
    content: str = "hello",
    author_id: int = 123,
    author_display_name: str = "TestUser",
    author_bot: bool = False,
    channel_id: int = 456,
    message_id: int = 789,
    guild_id: int | None = 1000,
    is_thread: bool = False,
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock discord.Message with the given attributes."""
    import discord

    msg = MagicMock(spec=discord.Message)

    # Author
    msg.author = MagicMock()
    msg.author.bot = author_bot
    msg.author.id = author_id
    msg.author.display_name = author_display_name

    # Channel
    if is_thread:
        msg.channel = MagicMock(spec=discord.Thread)
    else:
        msg.channel = MagicMock(spec=discord.TextChannel)
    msg.channel.id = channel_id

    # Message
    msg.content = content
    msg.id = message_id
    msg.created_at = created_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
    msg.attachments = []

    # Guild
    if guild_id is not None:
        msg.guild = MagicMock()
        msg.guild.id = guild_id
    else:
        msg.guild = None

    return msg


@pytest.mark.unit
class TestMessageToEnvelope:
    """Tests for message_to_envelope conversion."""

    def test_basic_message_conversion(self) -> None:
        msg = _make_discord_message(
            content="hello world",
            author_id=123,
            channel_id=456,
            message_id=789,
        )

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.channel_type == EnumChannelType.DISCORD
        assert envelope.channel_id == "456"
        assert envelope.sender_id == "123"
        assert envelope.sender_display_name == "TestUser"
        assert envelope.message_text == "hello world"
        assert envelope.message_id == "789"
        assert envelope.thread_id is None

    def test_bot_messages_are_skipped(self) -> None:
        msg = _make_discord_message(author_bot=True)

        envelope = message_to_envelope(msg)

        assert envelope is None

    def test_thread_message_sets_thread_id(self) -> None:
        msg = _make_discord_message(channel_id=999, is_thread=True)

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.thread_id == "999"

    def test_non_thread_message_has_no_thread_id(self) -> None:
        msg = _make_discord_message(is_thread=False)

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.thread_id is None

    def test_timestamp_is_preserved(self) -> None:
        ts = datetime(2026, 3, 15, 10, 30, 0, tzinfo=UTC)
        msg = _make_discord_message(created_at=ts)

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.timestamp == ts

    def test_naive_timestamp_gets_utc(self) -> None:
        naive_ts = datetime(2026, 3, 15, 10, 30, 0)  # noqa: DTZ001
        msg = _make_discord_message(created_at=naive_ts)

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.timestamp.tzinfo == UTC

    def test_correlation_id_is_generated(self) -> None:
        msg = _make_discord_message()

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.correlation_id is not None

    def test_empty_message_content(self) -> None:
        msg = _make_discord_message(content="")

        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.message_text == ""

    def test_dm_channel_no_guild(self) -> None:
        msg = _make_discord_message(guild_id=None)

        envelope = message_to_envelope(msg)

        assert envelope is not None
