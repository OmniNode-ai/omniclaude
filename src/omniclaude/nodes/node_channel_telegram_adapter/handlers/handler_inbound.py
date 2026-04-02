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

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


class ModelTelegramUser(BaseModel):
    """Typed representation of a Telegram user object."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int = Field(..., description="Telegram user ID")
    is_bot: bool = Field(default=False, description="Whether the user is a bot")
    first_name: str = Field(default="", description="User first name")
    last_name: str = Field(default="", description="User last name")


class ModelTelegramChat(BaseModel):
    """Typed representation of a Telegram chat object."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int = Field(..., description="Telegram chat ID")
    type: str = Field(default="private", description="Chat type")


class ModelTelegramMessage(BaseModel):
    """Typed representation of a Telegram message object."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    message_id: int = Field(..., description="Telegram message ID")
    chat: ModelTelegramChat = Field(..., description="Chat the message belongs to")
    from_user: ModelTelegramUser | None = Field(
        default=None,
        alias="from",
        description="Sender of the message",
    )
    text: str | None = Field(default=None, description="Message text")
    caption: str | None = Field(default=None, description="Media caption")
    date: int | float | None = Field(default=None, description="Unix timestamp")
    message_thread_id: int | None = Field(
        default=None, description="Thread/topic ID in supergroups"
    )


def message_to_envelope(
    message: ModelTelegramMessage | dict[str, object],
) -> ModelChannelEnvelope | None:
    """Convert a Telegram message to a normalized channel envelope.

    Accepts either a ``ModelTelegramMessage`` or a raw dict (auto-parsed).

    Args:
        message: Telegram message data.

    Returns:
        ModelChannelEnvelope if the message should be processed, None if
        the message should be skipped (e.g. bot messages).
    """
    if isinstance(message, dict):
        message = ModelTelegramMessage.model_validate(message)

    from_user = message.from_user
    if from_user is None or from_user.is_bot:
        return None

    # Telegram date is a Unix timestamp
    raw_date = message.date
    if isinstance(raw_date, int | float):
        timestamp = datetime.fromtimestamp(raw_date, tz=UTC)
    else:
        timestamp = datetime.now(tz=UTC)

    # Extract display name: first_name + optional last_name
    display_name = (
        f"{from_user.first_name} {from_user.last_name}".strip()
        if from_user.last_name
        else from_user.first_name
    )

    # Thread ID from Telegram topics/threads in supergroups
    thread_id: str | None = None
    if message.message_thread_id is not None:
        thread_id = str(message.message_thread_id)

    return ModelChannelEnvelope(
        channel_id=str(message.chat.id),
        channel_type=EnumChannelType.TELEGRAM,
        sender_id=str(from_user.id),
        sender_display_name=display_name or None,
        message_text=message.text or message.caption or "",
        message_id=str(message.message_id),
        thread_id=thread_id,
        timestamp=timestamp,
    )
