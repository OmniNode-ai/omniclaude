# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Telegram outbound handler.

Sends reply messages to Telegram chats via the Bot API.

Related:
    - OMN-7191: Telegram channel adapter contract package
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


class TelegramBot(Protocol):
    """Protocol for Telegram Bot API client (aiogram.Bot)."""

    async def send_message(self, **kwargs: Any) -> Any: ...


async def send_telegram_reply(
    reply: ModelChannelReply,
    *,
    bot: TelegramBot,
) -> None:
    """Send a reply to a Telegram chat.

    If ``reply.reply_to`` is set, the reply is sent as a reply to
    the original message via ``reply_to_message_id``.

    Args:
        reply: The channel reply to send.
        bot: A Telegram Bot instance.
    """
    kwargs: dict[str, Any] = {
        "chat_id": int(reply.channel_id),
        "text": reply.reply_text,
    }
    if reply.reply_to:
        kwargs["reply_to_message_id"] = int(reply.reply_to)

    logger.info(
        "Sending Telegram reply: chat_id=%s correlation_id=%s",
        reply.channel_id,
        reply.correlation_id,
    )

    await bot.send_message(**kwargs)
