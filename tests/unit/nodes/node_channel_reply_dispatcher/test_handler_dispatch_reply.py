# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for channel reply dispatch handler."""

from __future__ import annotations

from uuid import uuid4

import pytest
from omniclaude.enums.enum_channel_type import EnumChannelType

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_channel_reply_dispatcher.handlers.handler_dispatch_reply import (
    OUTBOUND_TOPIC_MAP,
    DispatchResult,
    handle_dispatch_reply,
)
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)


def _make_reply(**overrides: object) -> ModelChannelReply:
    defaults: dict[str, object] = {
        "reply_text": "Hello from OmniClaw",
        "channel_id": "general",
        "channel_type": EnumChannelType.DISCORD,
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelReply(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestHandlerDispatchReply:
    """Test cases for handle_dispatch_reply."""

    def test_discord_routes_correctly(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.DISCORD)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
        assert result.topic == TopicBase.CHANNEL_DISCORD_OUTBOUND

    def test_slack_routes_correctly(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.SLACK)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
        assert result.topic == TopicBase.CHANNEL_SLACK_OUTBOUND

    def test_telegram_routes_correctly(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.TELEGRAM)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
        assert result.topic == TopicBase.CHANNEL_TELEGRAM_OUTBOUND

    def test_email_routes_correctly(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.EMAIL)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
        assert result.topic == TopicBase.CHANNEL_EMAIL_OUTBOUND

    def test_sms_routes_correctly(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.SMS)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
        assert result.topic == TopicBase.CHANNEL_SMS_OUTBOUND

    def test_matrix_no_outbound_topic(self) -> None:
        reply = _make_reply(channel_type=EnumChannelType.MATRIX)
        result = handle_dispatch_reply(reply)
        assert result.routed is False
        assert result.topic is None

    def test_routing_table_is_declarative(self) -> None:
        assert isinstance(OUTBOUND_TOPIC_MAP, dict)
        assert len(OUTBOUND_TOPIC_MAP) == 5

    def test_dispatch_result_type(self) -> None:
        reply = _make_reply()
        result = handle_dispatch_reply(reply)
        assert isinstance(result, DispatchResult)

    def test_preserves_correlation_through_routing(self) -> None:
        cid = uuid4()
        reply = _make_reply(correlation_id=cid)
        result = handle_dispatch_reply(reply)
        assert result.routed is True
