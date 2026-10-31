# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Email outbound handler.

Sends reply messages via SMTP with proper threading headers.

Related:
    - OMN-7192: Email channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

from omniclaude.nodes.node_channel_email_adapter.models.model_email_reply_request import (
    ModelEmailReplyRequest,
    ModelEmailReplyResult,
)

logger = logging.getLogger(__name__)


class HandlerEmailOutbound:
    """Build the outgoing email for a channel reply."""

    def handle(self, request: ModelEmailReplyRequest) -> ModelEmailReplyResult:
        """Build an EmailMessage for the reply.

        Sets In-Reply-To and References headers when reply_to is present
        for proper threading in mail clients.

        Returns:
            The constructed EmailMessage, ready to send.
        """
        reply = request.reply
        msg = EmailMessage()
        msg["From"] = request.from_addr
        msg["To"] = request.to_addr
        msg["Subject"] = f"Re: {request.subject}" if request.subject else "Re:"

        if reply.reply_to:
            msg["In-Reply-To"] = reply.reply_to
            msg["References"] = reply.reply_to

        msg.set_content(reply.reply_text)

        logger.info(
            "Built email reply: correlation_id=%s",
            reply.correlation_id,
        )

        return ModelEmailReplyResult(message=msg)
