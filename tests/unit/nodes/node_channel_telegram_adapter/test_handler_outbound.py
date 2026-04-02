# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Telegram outbound handler."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)
from omniclaude.nodes.node_channel_telegram_adapter.handlers.handler_outbound import (
    send_telegram_reply,
)


def _make_reply(**overrides: object) -> ModelChannelReply:
    defaults: dict[str, object] = {
        "reply_text": "Hello from OmniClaw",
        "channel_id": "-100123",
        "channel_type": EnumChannelType.TELEGRAM,
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelReply(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSendTelegramReply:
    """Tests for send_telegram_reply."""

    @pytest.mark.asyncio
    async def test_sends_message_to_chat(self) -> None:
        bot = AsyncMock()
        reply = _make_reply()

        await send_telegram_reply(reply, bot=bot)

        bot.send_message.assert_called_once_with(
            chat_id=-100123,
            text="Hello from OmniClaw",
        )

    @pytest.mark.asyncio
    async def test_reply_to_sets_reply_to_message_id(self) -> None:
        bot = AsyncMock()
        reply = _make_reply(reply_to="42")

        await send_telegram_reply(reply, bot=bot)

        bot.send_message.assert_called_once_with(
            chat_id=-100123,
            text="Hello from OmniClaw",
            reply_to_message_id=42,
        )

    @pytest.mark.asyncio
    async def test_no_reply_to_omits_reply_to_message_id(self) -> None:
        bot = AsyncMock()
        reply = _make_reply(reply_to=None)

        await send_telegram_reply(reply, bot=bot)

        call_kwargs = bot.send_message.call_args[1]
        assert "reply_to_message_id" not in call_kwargs
