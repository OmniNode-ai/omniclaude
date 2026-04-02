# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Telegram inbound handler."""

from __future__ import annotations

from typing import Any

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_telegram_adapter.handlers.handler_inbound import (
    message_to_envelope,
)


def _make_telegram_message(**overrides: Any) -> dict[str, Any]:
    """Create a Telegram message dict with defaults."""
    defaults: dict[str, Any] = {
        "message_id": 42,
        "from": {
            "id": 789,
            "is_bot": False,
            "first_name": "Alice",
            "last_name": "Smith",
        },
        "chat": {"id": -100123, "type": "supergroup"},
        "text": "hello",
        "date": 1711929600,
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.unit
class TestMessageToEnvelope:
    """Tests for message_to_envelope conversion."""

    def test_basic_message_conversion(self) -> None:
        msg = _make_telegram_message()
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.channel_type == EnumChannelType.TELEGRAM
        assert envelope.channel_id == "-100123"
        assert envelope.sender_id == "789"
        assert envelope.sender_display_name == "Alice Smith"
        assert envelope.message_text == "hello"
        assert envelope.message_id == "42"

    def test_bot_messages_skipped(self) -> None:
        msg = _make_telegram_message()
        msg["from"]["is_bot"] = True
        assert message_to_envelope(msg) is None

    def test_no_from_user_skipped(self) -> None:
        msg = _make_telegram_message()
        del msg["from"]
        assert message_to_envelope(msg) is None

    def test_thread_id_from_message_thread_id(self) -> None:
        msg = _make_telegram_message(message_thread_id=99)
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.thread_id == "99"

    def test_no_thread_id_when_absent(self) -> None:
        msg = _make_telegram_message()
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.thread_id is None

    def test_caption_used_when_no_text(self) -> None:
        msg = _make_telegram_message(text=None, caption="photo caption")
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.message_text == "photo caption"

    def test_empty_text_when_no_text_or_caption(self) -> None:
        msg = _make_telegram_message(text=None)
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.message_text == ""

    def test_timestamp_from_unix(self) -> None:
        msg = _make_telegram_message(date=1711929600)
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.timestamp.year == 2024

    def test_first_name_only_display(self) -> None:
        msg = _make_telegram_message()
        msg["from"] = {"id": 1, "is_bot": False, "first_name": "Bob"}
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.sender_display_name == "Bob"

    def test_correlation_id_generated(self) -> None:
        msg = _make_telegram_message()
        envelope = message_to_envelope(msg)

        assert envelope is not None
        assert envelope.correlation_id is not None
