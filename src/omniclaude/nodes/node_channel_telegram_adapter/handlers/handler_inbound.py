# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Telegram inbound handler.

Converts Telegram message data into ModelChannelEnvelope instances
for publishing to the OmniClaw event bus. MVP supports text-first
flows only; media attachments are deferred.

Related:
    - OMN-7191: Telegram channel adapter contract package
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


def message_to_envelope(message: dict[str, Any]) -> ModelChannelEnvelope | None:
    """Convert a Telegram message dict to a normalized channel envelope.

    Accepts a dictionary representation of a Telegram message (as would be
    received from aiogram or the Bot API webhook). This avoids a hard
    dependency on aiogram at import time.

    Args:
        message: Telegram message data dict with keys: ``message_id``,
            ``chat``, ``from`` (aliased ``from_user``), ``text``, ``date``, etc.

    Returns:
        ModelChannelEnvelope if the message should be processed, None if
        the message should be skipped (e.g. bot messages).
    """
    from_user = message.get("from") or message.get("from_user")
    if from_user is None or from_user.get("is_bot", False):
        return None

    chat = message.get("chat", {})

    # Telegram date is a Unix timestamp
    raw_date = message.get("date")
    if isinstance(raw_date, datetime):
        timestamp = raw_date if raw_date.tzinfo else raw_date.replace(tzinfo=UTC)
    elif isinstance(raw_date, int | float):
        timestamp = datetime.fromtimestamp(raw_date, tz=UTC)
    else:
        timestamp = datetime.now(tz=UTC)

    # Extract display name: first_name + optional last_name
    first = from_user.get("first_name", "")
    last = from_user.get("last_name", "")
    display_name = f"{first} {last}".strip() if last else first

    # Thread ID from Telegram topics/threads in supergroups
    thread_id: str | None = None
    raw_thread = message.get("message_thread_id")
    if raw_thread is not None:
        thread_id = str(raw_thread)

    return ModelChannelEnvelope(
        channel_id=str(chat.get("id", "")),
        channel_type=EnumChannelType.TELEGRAM,
        sender_id=str(from_user.get("id", "")),
        sender_display_name=display_name or None,
        message_text=message.get("text") or message.get("caption") or "",
        message_id=str(message.get("message_id", "")),
        thread_id=thread_id,
        timestamp=timestamp,
    )
