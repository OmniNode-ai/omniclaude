# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SMS/Twilio outbound handler.

Sends reply messages via the Twilio Messages API.

Related:
    - OMN-7193: SMS/Twilio channel adapter contract package
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


class TwilioMessagesApi(Protocol):
    """Protocol for Twilio Messages API (twilio.rest.Client.messages)."""

    def create(
        self,
        *,
        body: str,
        from_: str,
        to: str,
    ) -> object: ...


async def send_sms_reply(
    reply: ModelChannelReply,
    *,
    messages_api: TwilioMessagesApi,
    from_number: str,
) -> None:
    """Send a reply via Twilio SMS.

    Args:
        reply: The channel reply to send.
        messages_api: Twilio client.messages interface.
        from_number: The Twilio phone number to send from.
    """
    logger.info(
        "Sending SMS reply: correlation_id=%s",
        reply.correlation_id,
    )

    await asyncio.to_thread(
        messages_api.create,
        body=reply.reply_text,
        from_=from_number,
        to=reply.channel_id,
    )
