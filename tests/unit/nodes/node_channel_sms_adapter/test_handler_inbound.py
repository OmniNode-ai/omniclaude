# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the SMS/Twilio inbound handler."""

from __future__ import annotations

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_sms_adapter.handlers.handler_inbound import (
    webhook_to_envelope,
)


def _make_twilio_payload(**overrides: str) -> dict[str, str]:
    """Create a Twilio webhook payload dict with defaults."""
    defaults: dict[str, str] = {
        "MessageSid": "SM1234567890abcdef",
        "From": "+15551234567",
        "To": "+15559876543",
        "Body": "Hello via SMS",
        "FromCity": "San Francisco",
        "AccountSid": "AC000000000000",
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.unit
class TestWebhookToEnvelope:
    """Tests for webhook_to_envelope conversion."""

    def test_basic_sms_conversion(self) -> None:
        payload = _make_twilio_payload()
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.channel_type == EnumChannelType.SMS
        assert envelope.channel_id == "+15559876543"
        assert envelope.sender_id == "+15551234567"
        assert envelope.sender_display_name == "San Francisco"
        assert envelope.message_text == "Hello via SMS"
        assert envelope.message_id == "SM1234567890abcdef"

    def test_missing_message_sid_returns_none(self) -> None:
        payload = _make_twilio_payload()
        del payload["MessageSid"]
        assert webhook_to_envelope(payload) is None

    def test_no_threading(self) -> None:
        payload = _make_twilio_payload()
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.thread_id is None

    def test_empty_body(self) -> None:
        payload = _make_twilio_payload(Body="")
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.message_text == ""

    def test_no_from_city(self) -> None:
        payload = _make_twilio_payload()
        del payload["FromCity"]
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.sender_display_name is None

    def test_timestamp_is_utc(self) -> None:
        from datetime import UTC

        payload = _make_twilio_payload()
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.timestamp.tzinfo == UTC

    def test_correlation_id_generated(self) -> None:
        payload = _make_twilio_payload()
        envelope = webhook_to_envelope(payload)

        assert envelope is not None
        assert envelope.correlation_id is not None
