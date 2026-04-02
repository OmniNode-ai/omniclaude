# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Slack inbound handler.

Converts Slack Events API message payloads into ModelChannelEnvelope
instances for publishing to the OmniClaw event bus.

Related:
    - OMN-7190: Slack channel adapter contract package
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


def event_to_envelope(event: dict[str, Any]) -> ModelChannelEnvelope | None:
    """Convert a Slack message event to a normalized channel envelope.

    Args:
        event: Slack Events API ``message`` event payload.

    Returns:
        ModelChannelEnvelope if the message should be processed, None if
        the message should be skipped (e.g. bot messages).
    """
    # Filter bot messages: Slack uses both patterns
    if event.get("subtype") == "bot_message" or "bot_id" in event:
        return None

    # Slack Events API does not include display name in message events;
    # resolving via users.info is deferred to avoid rate limiting.
    timestamp = datetime.fromtimestamp(float(event["ts"]), tz=UTC)

    return ModelChannelEnvelope(
        channel_id=event["channel"],
        channel_type=EnumChannelType.SLACK,
        sender_id=event.get("user", ""),
        sender_display_name=None,
        message_text=event.get("text", ""),
        message_id=event["ts"],
        thread_id=event.get("thread_ts"),
        timestamp=timestamp,
    )
