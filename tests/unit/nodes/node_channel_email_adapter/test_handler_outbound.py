# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the Email outbound handler."""

from __future__ import annotations

from uuid import uuid4

import pytest

from omniclaude.enums.enum_channel_type import EnumChannelType
from omniclaude.nodes.node_channel_email_adapter.handlers.handler_outbound import (
    build_reply_message,
)
from omniclaude.nodes.node_channel_reply_dispatcher.models.model_channel_reply import (
    ModelChannelReply,
)


def _make_reply(**overrides: object) -> ModelChannelReply:
    defaults: dict[str, object] = {
        "reply_text": "Hello from OmniClaw",
        "channel_id": "inbox@omninode.ai",
        "channel_type": EnumChannelType.EMAIL,
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelChannelReply(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestBuildReplyMessage:
    """Tests for build_reply_message."""

    def test_basic_reply(self) -> None:
        reply = _make_reply()
        msg = build_reply_message(
            reply,
            from_addr="bot@omninode.ai",
            to_addr="alice@example.com",
            subject="Help",
        )

        assert msg["From"] == "bot@omninode.ai"
        assert msg["To"] == "alice@example.com"
        assert msg["Subject"] == "Re: Help"
        assert "Hello from OmniClaw" in msg.get_content()

    def test_threading_headers_set(self) -> None:
        reply = _make_reply(reply_to="<msg-001@example.com>")
        msg = build_reply_message(
            reply,
            from_addr="bot@omninode.ai",
            to_addr="alice@example.com",
        )

        assert msg["In-Reply-To"] == "<msg-001@example.com>"
        assert msg["References"] == "<msg-001@example.com>"

    def test_no_reply_to_omits_threading(self) -> None:
        reply = _make_reply(reply_to=None)
        msg = build_reply_message(
            reply,
            from_addr="bot@omninode.ai",
            to_addr="alice@example.com",
        )

        assert msg["In-Reply-To"] is None
        assert msg["References"] is None

    def test_empty_subject(self) -> None:
        reply = _make_reply()
        msg = build_reply_message(
            reply,
            from_addr="bot@omninode.ai",
            to_addr="alice@example.com",
            subject="",
        )

        assert msg["Subject"] == "Re:"
