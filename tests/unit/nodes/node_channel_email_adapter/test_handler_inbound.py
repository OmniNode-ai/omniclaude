# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Email inbound handler."""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_email_adapter.handlers.handler_inbound import (
    email_to_envelope,
)


def _make_email(
    *,
    from_addr: str = "alice@example.com",
    from_display: str = "Alice",
    subject: str = "Help",
    body: str = "I need help",
    message_id: str = "<msg-001@example.com>",
    date: str = "Mon, 01 Apr 2024 12:00:00 +0000",
    in_reply_to: str | None = None,
    references: str | None = None,
) -> EmailMessage:
    """Create an email.message.EmailMessage with the given attributes."""
    msg = EmailMessage()
    msg["From"] = f"{from_display} <{from_addr}>" if from_display else from_addr
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    msg["Date"] = date
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    return msg


@pytest.mark.unit
class TestEmailToEnvelope:
    """Tests for email_to_envelope conversion."""

    def test_basic_email_conversion(self) -> None:
        msg = _make_email()
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.channel_type == EnumChannelType.EMAIL
        assert envelope.channel_id == "inbox@omninode.ai"
        assert envelope.sender_id == "alice@example.com"
        assert envelope.sender_display_name == "Alice"
        assert "I need help" in envelope.message_text
        assert envelope.message_id == "<msg-001@example.com>"

    def test_no_from_header_returns_none(self) -> None:
        msg = EmailMessage()
        msg["Subject"] = "test"
        msg.set_content("body")
        assert email_to_envelope(msg, mailbox="inbox@omninode.ai") is None

    def test_thread_id_from_in_reply_to(self) -> None:
        msg = _make_email(in_reply_to="<parent@example.com>")
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.thread_id == "<parent@example.com>"

    def test_thread_id_from_references_fallback(self) -> None:
        msg = _make_email(references="<first@example.com> <second@example.com>")
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.thread_id == "<second@example.com>"

    def test_in_reply_to_preferred_over_references(self) -> None:
        msg = _make_email(
            in_reply_to="<direct@example.com>",
            references="<other@example.com>",
        )
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.thread_id == "<direct@example.com>"

    def test_no_threading_headers(self) -> None:
        msg = _make_email()
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.thread_id is None

    def test_timestamp_parsed(self) -> None:
        msg = _make_email(date="Mon, 01 Apr 2024 12:00:00 +0000")
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.timestamp.year == 2024

    def test_no_display_name(self) -> None:
        msg = _make_email(from_display="", from_addr="plain@example.com")
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.sender_display_name is None

    def test_correlation_id_generated(self) -> None:
        msg = _make_email()
        envelope = email_to_envelope(msg, mailbox="inbox@omninode.ai")

        assert envelope is not None
        assert envelope.correlation_id is not None
