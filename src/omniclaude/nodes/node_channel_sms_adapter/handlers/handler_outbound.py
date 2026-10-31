# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SMS/Twilio outbound handler.

Sends reply messages via the Twilio Messages API.

Related:
    - OMN-7193: SMS/Twilio channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)
from omniclaude.nodes.node_channel_sms_adapter.models.model_sms_outbound_result import (
    ModelSmsOutboundResult,
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


class HandlerSmsOutbound:
    """Send a channel reply through the Twilio Messages API."""

    def __init__(self, messages_api: TwilioMessagesApi, from_number: str) -> None:
        self._messages_api = messages_api
        self._from_number = from_number

    async def handle(self, request: ModelChannelReply) -> ModelSmsOutboundResult:
        """Send a reply via Twilio SMS."""
        logger.info(
            "Sending SMS reply: correlation_id=%s",
            request.correlation_id,
        )

        await asyncio.to_thread(
            self._messages_api.create,
            body=request.reply_text,
            from_=self._from_number,
            to=request.channel_id,
        )
        return ModelSmsOutboundResult(delivered=True)
