# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the SMS/Twilio outbound handler."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)
from omniclaude.nodes.node_channel_sms_adapter.handlers.handler_outbound import (
    HandlerSmsOutbound,
)


def _make_reply(**overrides: object) -> ModelChannelReply:
    defaults: dict[str, object] = {
        "reply_text": "Hello from OmniClaw",
        "channel_id": "+15551234567",
        "channel_type": EnumChannelType.SMS,
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelReply(**defaults)  # type: ignore[arg-type]


async def send_sms_reply(
    reply: ModelChannelReply, *, messages_api: MagicMock, from_number: str
) -> bool:
    """Run the handler on one reply and return whether it was delivered."""
    result = await HandlerSmsOutbound(messages_api, from_number).handle(reply)
    return result.delivered


@pytest.mark.unit
class TestSendSmsReply:
    """Tests for HandlerSmsOutbound.handle."""

    @pytest.mark.asyncio
    async def test_sends_sms(self) -> None:
        messages_api = MagicMock()
        reply = _make_reply()

        assert await send_sms_reply(
            reply,
            messages_api=messages_api,
            from_number="+15559876543",
        )

        messages_api.create.assert_called_once_with(
            body="Hello from OmniClaw",
            from_="+15559876543",
            to="+15551234567",
        )

    @pytest.mark.asyncio
    async def test_uses_channel_id_as_to(self) -> None:
        messages_api = MagicMock()
        reply = _make_reply(channel_id="+15550001111")

        await send_sms_reply(
            reply,
            messages_api=messages_api,
            from_number="+15559876543",
        )

        call_kwargs = messages_api.create.call_args[1]
        assert call_kwargs["to"] == "+15550001111"
