# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Email inbound handler.

Parses email.message.EmailMessage objects into ModelChannelEnvelope
instances. Plain-text body preferred; threading derived from
In-Reply-To / References headers (heuristic).

Related:
    - OMN-7192: Email channel adapter contract package
    - OMN-21536: handler-shape burn-down
"""

from __future__ import annotations

import email.utils
import logging
from email.message import EmailMessage

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_email_adapter.models.model_email_inbound_request import (
    ModelEmailInboundRequest,
)
from omniclaude.nodes.node_channel_email_adapter.models.model_email_inbound_result import (
    ModelEmailInboundResult,
)
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


class HandlerEmailInbound:
    """Convert an email message to a normalized channel envelope."""

    def handle(self, request: ModelEmailInboundRequest) -> ModelEmailInboundResult:
        """Convert the request's email message.

        Returns:
            A result whose envelope is set, or None if the message cannot be
            parsed.
        """
        msg = request.message
        from_header = msg.get("From", "")
        if not from_header:
            return ModelEmailInboundResult(envelope=None)

        # Extract plain-text body
        body = msg.get_body(preferencelist=("plain",))
        text = body.get_content() if body else ""

        # Extract sender display name from "Display Name <email>" format
        display_name, sender_addr = email.utils.parseaddr(from_header)

        # Thread ID from In-Reply-To or last entry in References
        thread_id = _extract_thread_id(msg)

        # Parse date — always produce a UTC-aware datetime
        from datetime import UTC, datetime

        date_header = msg.get("Date")
        timestamp = (
            email.utils.parsedate_to_datetime(date_header) if date_header else None
        )
        if timestamp is None:
            timestamp = datetime.now(tz=UTC)
        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        else:
            timestamp = timestamp.astimezone(UTC)

        return ModelEmailInboundResult(
            envelope=ModelChannelEnvelope(
                channel_id=request.mailbox,
                channel_type=EnumChannelType.EMAIL,
                sender_id=sender_addr or from_header,
                sender_display_name=display_name or None,
                message_text=text,
                message_id=msg.get("Message-ID"),
                thread_id=thread_id,
                timestamp=timestamp,
            )
        )


def _extract_thread_id(msg: EmailMessage) -> str | None:
    """Extract thread identifier from email headers.

    Prefers In-Reply-To; falls back to the last entry in References.
    """
    in_reply_to = msg.get("In-Reply-To")
    if isinstance(in_reply_to, str) and in_reply_to:
        return in_reply_to.strip()

    references = msg.get("References", "")
    if isinstance(references, str) and references:
        parts = references.strip().split()
        if parts:
            return parts[-1]

    return None
