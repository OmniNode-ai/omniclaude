# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SMS/Twilio inbound handler.

Converts Twilio webhook payloads into ModelChannelEnvelope instances
for publishing to the OmniClaw event bus.

Related:
    - OMN-7193: SMS/Twilio channel adapter contract package
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


def webhook_to_envelope(payload: dict[str, str]) -> ModelChannelEnvelope | None:
    """Convert a Twilio webhook payload to a normalized channel envelope.

    Args:
        payload: Twilio SMS webhook form data dict with keys:
            ``From``, ``To``, ``Body``, ``MessageSid``, etc.

    Returns:
        ModelChannelEnvelope if the payload is valid, None otherwise.
    """
    message_sid = payload.get("MessageSid")
    if not message_sid:
        logger.warning("Twilio webhook missing MessageSid, skipping")
        return None

    from_number = payload.get("From", "")
    to_number = payload.get("To", "")

    return ModelChannelEnvelope(
        channel_id=to_number,
        channel_type=EnumChannelType.SMS,
        sender_id=from_number,
        sender_display_name=payload.get("FromCity") or None,
        message_text=payload.get("Body", ""),
        message_id=message_sid,
        thread_id=None,  # SMS has no native threading
        timestamp=datetime.now(tz=UTC),
    )
