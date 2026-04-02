# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Slack outbound handler."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)
from omniclaude.nodes.node_channel_slack_adapter.handlers.handler_outbound import (
    send_slack_reply,
)


def _make_reply(**overrides: object) -> ModelChannelReply:
    defaults: dict[str, object] = {
        "reply_text": "Hello from OmniClaw",
        "channel_id": "C456",
        "channel_type": EnumChannelType.SLACK,
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelReply(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestSendSlackReply:
    """Tests for send_slack_reply."""

    @pytest.mark.asyncio
    async def test_sends_message_to_channel(self) -> None:
        client = MagicMock()
        reply = _make_reply()

        await send_slack_reply(reply, client=client)

        client.chat_postMessage.assert_called_once_with(
            channel="C456",
            text="Hello from OmniClaw",
        )

    @pytest.mark.asyncio
    async def test_threaded_reply_passes_thread_ts(self) -> None:
        client = MagicMock()
        reply = _make_reply(reply_to="1711929500.000000")

        await send_slack_reply(reply, client=client)

        client.chat_postMessage.assert_called_once_with(
            channel="C456",
            text="Hello from OmniClaw",
            thread_ts="1711929500.000000",
        )

    @pytest.mark.asyncio
    async def test_no_reply_to_omits_thread_ts(self) -> None:
        client = MagicMock()
        reply = _make_reply(reply_to=None)

        await send_slack_reply(reply, client=client)

        call_kwargs = client.chat_postMessage.call_args[1]
        assert "thread_ts" not in call_kwargs
