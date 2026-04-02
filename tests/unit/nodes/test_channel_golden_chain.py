# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Golden chain integration test for OmniClaw channel message flow.

Proves the core loop without any real channel or Kafka:
  channel-message-received -> orchestrator -> channel-reply-requested
  -> dispatcher -> channel-specific outbound topic

The test wires both handlers in-process and verifies the full pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_channel_orchestrator.handlers.handler_channel_orchestrate import (
    handle_channel_orchestrate,
)
from omniclaude.nodes.node_channel_reply_dispatcher.handlers.handler_dispatch_reply import (
    handle_dispatch_reply,
)
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)


@pytest.mark.unit
class TestChannelGoldenChain:
    """End-to-end integration test for the channel message pipeline."""

    def test_discord_message_flows_through_pipeline(self) -> None:
        """Full pipeline: message received -> orchestrate -> dispatch to discord outbound."""
        correlation_id = uuid4()

        # Step 1: Simulate inbound channel message
        envelope = ModelChannelEnvelope(
            channel_id="general",
            channel_type=EnumChannelType.DISCORD,
            sender_id="user-42",
            sender_display_name="Alice",
            message_text="What is ONEX?",
            message_id="msg-001",
            thread_id="thread-10",
            timestamp=datetime.now(tz=UTC),
            correlation_id=correlation_id,
        )

        # Step 2: Orchestrator processes the message
        orchestrator_output = handle_channel_orchestrate(envelope)

        # Verify orchestrator output
        assert orchestrator_output.reply_text, "Reply text must be non-empty"
        assert orchestrator_output.channel_type == EnumChannelType.DISCORD
        assert orchestrator_output.channel_id == "general"
        assert orchestrator_output.reply_to == "msg-001"
        assert orchestrator_output.thread_id == "thread-10"
        assert orchestrator_output.correlation_id == correlation_id

        # Step 3: Build reply model from orchestrator output (simulates Kafka serialization)
        reply = ModelChannelReply(
            reply_text=orchestrator_output.reply_text,
            channel_id=orchestrator_output.channel_id,
            channel_type=orchestrator_output.channel_type,
            reply_to=orchestrator_output.reply_to,
            thread_id=orchestrator_output.thread_id,
            correlation_id=orchestrator_output.correlation_id,
        )

        # Step 4: Dispatcher routes to channel-specific outbound topic
        dispatch_result = handle_dispatch_reply(reply)

        # Verify dispatch result
        assert dispatch_result.routed is True
        assert dispatch_result.topic == TopicBase.CHANNEL_DISCORD_OUTBOUND
        assert dispatch_result.error is None

    def test_slack_message_flows_through_pipeline(self) -> None:
        """Verify Slack messages route to the correct outbound topic."""
        correlation_id = uuid4()

        envelope = ModelChannelEnvelope(
            channel_id="C-random-slack",
            channel_type=EnumChannelType.SLACK,
            sender_id="U12345",
            message_text="Deploy status?",
            message_id="slack-msg-001",
            timestamp=datetime.now(tz=UTC),
            correlation_id=correlation_id,
        )

        orchestrator_output = handle_channel_orchestrate(envelope)
        assert orchestrator_output.channel_type == EnumChannelType.SLACK

        reply = ModelChannelReply(
            reply_text=orchestrator_output.reply_text,
            channel_id=orchestrator_output.channel_id,
            channel_type=orchestrator_output.channel_type,
            reply_to=orchestrator_output.reply_to,
            thread_id=orchestrator_output.thread_id,
            correlation_id=orchestrator_output.correlation_id,
        )

        dispatch_result = handle_dispatch_reply(reply)
        assert dispatch_result.routed is True
        assert dispatch_result.topic == TopicBase.CHANNEL_SLACK_OUTBOUND

    def test_correlation_id_threaded_through_full_chain(self) -> None:
        """Verify correlation_id is preserved from input to final dispatch."""
        correlation_id = uuid4()

        envelope = ModelChannelEnvelope(
            channel_id="room-1",
            channel_type=EnumChannelType.TELEGRAM,
            sender_id="tg-user-99",
            message_text="Hello",
            message_id="tg-msg-1",
            timestamp=datetime.now(tz=UTC),
            correlation_id=correlation_id,
        )

        output = handle_channel_orchestrate(envelope)
        assert output.correlation_id == correlation_id

        reply = ModelChannelReply(
            reply_text=output.reply_text,
            channel_id=output.channel_id,
            channel_type=output.channel_type,
            reply_to=output.reply_to,
            thread_id=output.thread_id,
            correlation_id=output.correlation_id,
        )
        assert reply.correlation_id == correlation_id

    def test_all_supported_channels_route_correctly(self) -> None:
        """Verify all channels with outbound topics route through the full chain."""
        expected_topics = {
            EnumChannelType.DISCORD: TopicBase.CHANNEL_DISCORD_OUTBOUND,
            EnumChannelType.SLACK: TopicBase.CHANNEL_SLACK_OUTBOUND,
            EnumChannelType.TELEGRAM: TopicBase.CHANNEL_TELEGRAM_OUTBOUND,
            EnumChannelType.EMAIL: TopicBase.CHANNEL_EMAIL_OUTBOUND,
            EnumChannelType.SMS: TopicBase.CHANNEL_SMS_OUTBOUND,
        }

        for channel_type, expected_topic in expected_topics.items():
            envelope = ModelChannelEnvelope(
                channel_id=f"ch-{channel_type.value}",
                channel_type=channel_type,
                sender_id="sender-1",
                message_text="test",
                message_id=f"msg-{channel_type.value}",
                timestamp=datetime.now(tz=UTC),
            )

            output = handle_channel_orchestrate(envelope)
            reply = ModelChannelReply(
                reply_text=output.reply_text,
                channel_id=output.channel_id,
                channel_type=output.channel_type,
                reply_to=output.reply_to,
                thread_id=output.thread_id,
                correlation_id=output.correlation_id,
            )
            result = handle_dispatch_reply(reply)

            assert result.routed is True, f"{channel_type.value} should route"
            assert result.topic == expected_topic, (
                f"{channel_type.value}: expected {expected_topic}, got {result.topic}"
            )
