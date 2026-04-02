# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Slack outbound handler.

Sends reply messages to Slack channels via the Web API.

Related:
    - OMN-7190: Slack channel adapter contract package
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


class SlackWebClient(Protocol):
    """Protocol for Slack Web API client (slack_sdk.WebClient)."""

    def chat_postMessage(self, **kwargs: Any) -> Any: ...  # noqa: N802


async def send_slack_reply(
    reply: ModelChannelReply,
    *,
    client: SlackWebClient,
) -> None:
    """Send a reply to a Slack channel.

    If ``reply.reply_to`` is set, the reply is sent as a threaded
    message using ``thread_ts``.

    Args:
        reply: The channel reply to send.
        client: A Slack WebClient instance.
    """
    kwargs: dict[str, Any] = {
        "channel": reply.channel_id,
        "text": reply.reply_text,
    }
    if reply.reply_to:
        kwargs["thread_ts"] = reply.reply_to

    logger.info(
        "Sending Slack reply: channel=%s correlation_id=%s",
        reply.channel_id,
        reply.correlation_id,
    )

    client.chat_postMessage(**kwargs)
