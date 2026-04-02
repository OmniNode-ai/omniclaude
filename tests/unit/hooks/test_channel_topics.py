# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OmniClaw channel messaging topics."""

from __future__ import annotations

import pytest

from omniclaude.hooks.topics import TopicBase, build_topic


@pytest.mark.unit
class TestChannelTopics:
    """Test cases for OmniClaw channel topics in TopicBase."""

    def test_channel_message_received(self) -> None:
        assert (
            TopicBase.CHANNEL_MESSAGE_RECEIVED
            == "onex.cmd.omniclaw.channel-message-received.v1"
        )

    def test_channel_reply_requested(self) -> None:
        assert (
            TopicBase.CHANNEL_REPLY_REQUESTED
            == "onex.evt.omniclaw.channel-reply-requested.v1"
        )

    def test_channel_message_processed(self) -> None:
        assert (
            TopicBase.CHANNEL_MESSAGE_PROCESSED
            == "onex.evt.omniclaw.channel-message-processed.v1"
        )

    def test_build_topic_channel_message_received(self) -> None:
        result = build_topic(TopicBase.CHANNEL_MESSAGE_RECEIVED)
        assert result == "onex.cmd.omniclaw.channel-message-received.v1"

    def test_build_topic_channel_reply_requested(self) -> None:
        result = build_topic(TopicBase.CHANNEL_REPLY_REQUESTED)
        assert result == "onex.evt.omniclaw.channel-reply-requested.v1"

    def test_build_topic_channel_message_processed(self) -> None:
        result = build_topic(TopicBase.CHANNEL_MESSAGE_PROCESSED)
        assert result == "onex.evt.omniclaw.channel-message-processed.v1"

    def test_topics_are_strenum_members(self) -> None:
        assert isinstance(TopicBase.CHANNEL_MESSAGE_RECEIVED, str)
        assert isinstance(TopicBase.CHANNEL_REPLY_REQUESTED, str)
        assert isinstance(TopicBase.CHANNEL_MESSAGE_PROCESSED, str)
