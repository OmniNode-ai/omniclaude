# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Slack inbound handler."""

from __future__ import annotations

from typing import Any

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_slack_adapter.handlers.handler_inbound import (
    event_to_envelope,
)


def _make_slack_event(**overrides: Any) -> dict[str, Any]:
    """Create a Slack message event payload with defaults."""
    defaults: dict[str, Any] = {
        "channel": "C456",
        "user": "U123",
        "text": "hello",
        "ts": "1711929600.123456",
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.unit
class TestEventToEnvelope:
    """Tests for event_to_envelope conversion."""

    def test_basic_message_conversion(self) -> None:
        event = _make_slack_event()
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.channel_type == EnumChannelType.SLACK
        assert envelope.channel_id == "C456"
        assert envelope.sender_id == "U123"
        assert envelope.message_text == "hello"
        assert envelope.message_id == "1711929600.123456"

    def test_bot_message_subtype_skipped(self) -> None:
        event = _make_slack_event(subtype="bot_message")
        assert event_to_envelope(event) is None

    def test_bot_id_present_skipped(self) -> None:
        event = _make_slack_event(bot_id="B999")
        assert event_to_envelope(event) is None

    def test_thread_ts_sets_thread_id(self) -> None:
        event = _make_slack_event(thread_ts="1711929500.000000")
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.thread_id == "1711929500.000000"

    def test_no_thread_ts_is_none(self) -> None:
        event = _make_slack_event()
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.thread_id is None

    def test_display_name_is_none(self) -> None:
        """Slack Events API does not include display name."""
        event = _make_slack_event()
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.sender_display_name is None

    def test_empty_text(self) -> None:
        event = _make_slack_event(text="")
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.message_text == ""

    def test_missing_text_defaults_empty(self) -> None:
        event = _make_slack_event()
        del event["text"]
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.message_text == ""

    def test_timestamp_parsed_from_ts(self) -> None:
        event = _make_slack_event(ts="1711929600.123456")
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.timestamp.year == 2024

    def test_correlation_id_generated(self) -> None:
        event = _make_slack_event()
        envelope = event_to_envelope(event)

        assert envelope is not None
        assert envelope.correlation_id is not None
