# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Email inbound handler.

Parses email.message.EmailMessage objects into ModelChannelEnvelope
instances. Plain-text body preferred; threading derived from
In-Reply-To / References headers (heuristic).

Related:
    - OMN-7192: Email channel adapter contract package
"""

from __future__ import annotations

import email.utils
import logging
from email.message import EmailMessage

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.shared.models.model_channel_envelope import ModelChannelEnvelope

logger = logging.getLogger(__name__)


def email_to_envelope(
    msg: EmailMessage,
    *,
    mailbox: str,
) -> ModelChannelEnvelope | None:
    """Convert an email message to a normalized channel envelope.

    Args:
        msg: Parsed email.message.EmailMessage.
        mailbox: The mailbox address this was received on (used as channel_id).

    Returns:
        ModelChannelEnvelope, or None if the message cannot be parsed.
    """
    from_header = msg.get("From", "")
    if not from_header:
        return None

    # Extract plain-text body
    body = msg.get_body(preferencelist=("plain",))
    text = body.get_content() if body else ""

    # Extract sender display name from "Display Name <email>" format
    display_name, sender_addr = email.utils.parseaddr(from_header)

    # Thread ID from In-Reply-To or last entry in References
    thread_id = _extract_thread_id(msg)

    # Parse date
    date_header = msg.get("Date")
    timestamp = email.utils.parsedate_to_datetime(date_header) if date_header else None
    if timestamp is None:
        from datetime import UTC, datetime

        timestamp = datetime.now(tz=UTC)

    return ModelChannelEnvelope(
        channel_id=mailbox,
        channel_type=EnumChannelType.EMAIL,
        sender_id=sender_addr or from_header,
        sender_display_name=display_name or None,
        message_text=text,
        message_id=msg.get("Message-ID"),
        thread_id=thread_id,
        timestamp=timestamp,
    )


def _extract_thread_id(msg: EmailMessage) -> str | None:
    """Extract thread identifier from email headers.

    Prefers In-Reply-To; falls back to the last entry in References.
    """
    in_reply_to = msg.get("In-Reply-To")
    if in_reply_to:
        return in_reply_to.strip()

    references = msg.get("References", "")
    if references:
        parts = references.strip().split()
        if parts:
            return parts[-1]

    return None
