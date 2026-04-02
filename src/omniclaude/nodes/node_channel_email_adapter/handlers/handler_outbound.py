# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Email outbound handler.

Sends reply messages via SMTP with proper threading headers.

Related:
    - OMN-7192: Email channel adapter contract package
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)

logger = logging.getLogger(__name__)


def build_reply_message(
    reply: ModelChannelReply,
    *,
    from_addr: str,
    to_addr: str,
    subject: str = "",
) -> EmailMessage:
    """Build an EmailMessage for the reply.

    Sets In-Reply-To and References headers when reply_to is present
    for proper threading in mail clients.

    Args:
        reply: The channel reply to send.
        from_addr: Sender email address.
        to_addr: Recipient email address.
        subject: Email subject line.

    Returns:
        Constructed EmailMessage ready to send.
    """
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = f"Re: {subject}" if subject else "Re:"

    if reply.reply_to:
        msg["In-Reply-To"] = reply.reply_to
        msg["References"] = reply.reply_to

    msg.set_content(reply.reply_text)

    logger.info(
        "Built email reply: correlation_id=%s",
        reply.correlation_id,
    )

    return msg
