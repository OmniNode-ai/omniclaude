# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Channel reply dispatch handler.

Routes reply-requested events to channel-specific outbound topics
using a declarative routing table keyed by EnumChannelType.

Related:
    - OMN-7187: Channel reply dispatcher node
    - OmniClaw MVP Part 1: Prerequisites
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from omniclaude.enums.enum_channel_type import EnumChannelType  # noqa: TC002

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


OUTBOUND_TOPIC_MAP: dict[EnumChannelType, str] = {
    EnumChannelType.DISCORD: TopicBase.CHANNEL_DISCORD_OUTBOUND,
    EnumChannelType.SLACK: TopicBase.CHANNEL_SLACK_OUTBOUND,
    EnumChannelType.TELEGRAM: TopicBase.CHANNEL_TELEGRAM_OUTBOUND,
    EnumChannelType.EMAIL: TopicBase.CHANNEL_EMAIL_OUTBOUND,
    EnumChannelType.SMS: TopicBase.CHANNEL_SMS_OUTBOUND,
}


@dataclass(frozen=True)
class DispatchResult:
    """Result of a reply dispatch operation."""

    routed: bool
    topic: str | None = None
    error: str | None = None


def handle_dispatch_reply(reply: ModelChannelReply) -> DispatchResult:
    """Route a reply to the appropriate channel-specific outbound topic.

    Args:
        reply: Channel reply with routing metadata.

    Returns:
        DispatchResult indicating success/failure and the target topic.
    """
    topic = OUTBOUND_TOPIC_MAP.get(reply.channel_type)

    if topic is None:
        logger.warning(
            "No outbound topic for channel_type=%s correlation_id=%s",
            reply.channel_type,
            reply.correlation_id,
        )
        return DispatchResult(
            routed=False,
            error=f"no_outbound_topic_for_{reply.channel_type.value}",
        )

    logger.info(
        "Dispatch reply: channel_type=%s topic=%s correlation_id=%s",
        reply.channel_type,
        topic,
        reply.correlation_id,
    )

    return DispatchResult(routed=True, topic=topic)
