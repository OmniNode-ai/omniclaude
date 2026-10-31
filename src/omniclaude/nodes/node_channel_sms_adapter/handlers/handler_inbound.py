# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SMS/Twilio inbound handler.

Converts Twilio webhook payloads into ModelChannelEnvelope instances
for publishing to the OmniClaw event bus.

Related:
    - OMN-7193: SMS/Twilio channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_sms_adapter.models.model_sms_inbound_result import (
    ModelSmsInboundResult,
)
from omniclaude.nodes.node_channel_sms_adapter.models.model_sms_webhook_request import (
    ModelSmsWebhookRequest,
)
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


class HandlerSmsInbound:
    """Convert a Twilio webhook to a normalized channel envelope."""

    def handle(self, request: ModelSmsWebhookRequest) -> ModelSmsInboundResult:
        """Convert the request's Twilio SMS webhook.

        Returns:
            A result whose envelope is set if the webhook is valid, and None
            otherwise.
        """
        if not request.message_sid:
            logger.warning("Twilio webhook missing MessageSid, skipping")
            return ModelSmsInboundResult(envelope=None)

        return ModelSmsInboundResult(
            envelope=ModelChannelEnvelope(
                channel_id=request.to_number,
                channel_type=EnumChannelType.SMS,
                sender_id=request.from_number,
                sender_display_name=request.from_city or None,
                message_text=request.body,
                message_id=request.message_sid,
                thread_id=None,  # SMS has no native threading
                timestamp=datetime.now(tz=UTC),
            )
        )
