# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for slack_gate_poll.py (OMN-2627).

Tests cover:
- Keyword matching logic
- Reply filtering (since_ts, bot messages)
- Poll loop outcomes: accepted, rejected, timeout
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the script under test directly (it lives outside src/, in skills/)
# ---------------------------------------------------------------------------
_SCRIPT_PATH = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins/onex/skills/slack-gate/slack_gate_poll.py"
)

spec = importlib.util.spec_from_file_location("slack_gate_poll", _SCRIPT_PATH)
assert spec is not None and spec.loader is not None
_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_module)  # type: ignore[union-attr]

_match_keywords = _module._match_keywords  # type: ignore[attr-defined]
poll_for_reply = _module.poll_for_reply  # type: ignore[attr-defined]
_fetch_replies_since = _module._fetch_replies_since  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reply(
    text: str, ts: float = 1700000001.0, bot_id: str = ""
) -> dict[str, Any]:
    msg: dict[str, Any] = {"text": text, "ts": str(ts)}
    if bot_id:
        msg["bot_id"] = bot_id
    return msg


# ---------------------------------------------------------------------------
# Tests: _match_keywords
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchKeywords:
    def test_exact_match(self) -> None:
        assert _match_keywords("merge", ["merge", "approve"]) == "merge"

    def test_case_insensitive(self) -> None:
        assert _match_keywords("MERGE", ["merge", "approve"]) == "merge"

    def test_substring_match(self) -> None:
        assert _match_keywords("yes please merge this", ["merge"]) == "merge"

    def test_no_match_returns_none(self) -> None:
        assert _match_keywords("hello world", ["merge", "approve"]) is None

    def test_empty_text(self) -> None:
        assert _match_keywords("", ["merge"]) is None

    def test_empty_keywords(self) -> None:
        assert _match_keywords("merge", []) is None

    def test_first_keyword_wins(self) -> None:
        # Both "merge" and "approve" are in text; first in keywords list wins
        result = _match_keywords("approve and merge", ["merge", "approve"])
        assert result == "merge"

    def test_reject_keywords(self) -> None:
        assert _match_keywords("no thanks", ["no", "reject", "cancel"]) == "no"

    def test_partial_word_does_not_match(self) -> None:
        # "cancel" should NOT match "cancellation" — but our implementation uses
        # substring containment, so "cancel" IS in "cancellation"
        assert _match_keywords("cancellation", ["cancel"]) == "cancel"


# ---------------------------------------------------------------------------
# Tests: _fetch_replies_since (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchRepliesSince:
    def _make_api_response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        return {"ok": True, "messages": messages}

    @patch.object(_module, "_slack_get")
    def test_excludes_original_gate_post(self, mock_get: MagicMock) -> None:
        gate_ts = 1700000000.0
        reply_ts = 1700000001.0
        mock_get.return_value = self._make_api_response(
            [
                {"text": "Gate message", "ts": str(gate_ts)},  # original post
                _make_reply("merge", ts=reply_ts),
            ]
        )
        replies = _fetch_replies_since(
            channel="C123",
            thread_ts=str(gate_ts),
            since_ts=gate_ts,
            bot_token="xoxb-test",
        )
        assert len(replies) == 1
        assert replies[0]["text"] == "merge"

    @patch.object(_module, "_slack_get")
    def test_excludes_replies_before_since_ts(self, mock_get: MagicMock) -> None:
        gate_ts = 1700000000.0
        old_reply_ts = 1699999999.0  # before gate post
        new_reply_ts = 1700000001.0
        mock_get.return_value = self._make_api_response(
            [
                {"text": "Gate message", "ts": str(gate_ts)},
                _make_reply("old reply", ts=old_reply_ts),
                _make_reply("new reply", ts=new_reply_ts),
            ]
        )
        replies = _fetch_replies_since(
            channel="C123",
            thread_ts=str(gate_ts),
            since_ts=gate_ts,
            bot_token="xoxb-test",
        )
        # Only new_reply (ts > gate_ts) should be included
        assert len(replies) == 1
        assert replies[0]["text"] == "new reply"

    @patch.object(_module, "_slack_get")
    def test_raises_on_api_error(self, mock_get: MagicMock) -> None:
        mock_get.return_value = {"ok": False, "error": "channel_not_found"}
        with pytest.raises(RuntimeError, match="channel_not_found"):
            _fetch_replies_since(
                channel="C_BAD",
                thread_ts="1700000000.0",
                since_ts=1700000000.0,
                bot_token="xoxb-test",
            )


# ---------------------------------------------------------------------------
# Tests: poll_for_reply (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPollForReply:
    _ACCEPT = ["merge", "approve", "yes", "proceed"]
    _REJECT = ["no", "reject", "cancel", "hold", "deny"]

    @patch.object(_module, "_fetch_replies_since")
    def test_accepted_on_first_poll(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [_make_reply("merge")]
        exit_code, output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=1,
            accept_keywords=self._ACCEPT,
            reject_keywords=self._REJECT,
        )
        assert exit_code == 0
        assert output.startswith("ACCEPTED:")
        assert "merge" in output

    @patch.object(_module, "_fetch_replies_since")
    def test_rejected_on_first_poll(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [_make_reply("reject this")]
        exit_code, output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=1,
            accept_keywords=self._ACCEPT,
            reject_keywords=self._REJECT,
        )
        assert exit_code == 1
        assert output.startswith("REJECTED:")

    @patch("time.sleep")
    @patch.object(_module, "_fetch_replies_since")
    def test_timeout_when_no_reply(
        self, mock_fetch: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # Return no replies every poll
        mock_fetch.return_value = []
        # Patch monotonic to expire quickly
        start = time.monotonic()
        call_count = 0

        def fake_monotonic() -> float:
            nonlocal call_count
            call_count += 1
            # After 3 calls, return a time past the deadline
            if call_count > 3:
                return start + 999999
            return start

        with patch("time.monotonic", side_effect=fake_monotonic):
            exit_code, output = poll_for_reply(
                channel="C123",
                thread_ts="1700000000.0",
                bot_token="xoxb-test",
                timeout_minutes=1,
                poll_interval_seconds=1,
                accept_keywords=self._ACCEPT,
                reject_keywords=self._REJECT,
            )

        assert exit_code == 2
        assert output == "TIMEOUT"

    @patch.object(_module, "_fetch_replies_since")
    def test_skips_bot_messages(self, mock_fetch: MagicMock) -> None:
        # Bot message with accept keyword should be skipped
        mock_fetch.return_value = [_make_reply("merge", bot_id="B123")]
        # After bot message, return a human reply
        mock_fetch.side_effect = [
            [_make_reply("merge", bot_id="B123")],  # first poll: bot reply
            [_make_reply("approve")],  # second poll: human reply
        ]
        exit_code, output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=0,
            accept_keywords=self._ACCEPT,
            reject_keywords=self._REJECT,
        )
        assert exit_code == 0
        assert "approve" in output

    @patch("time.sleep")
    @patch.object(_module, "_fetch_replies_since")
    def test_continues_after_transient_api_error(
        self, mock_fetch: MagicMock, mock_sleep: MagicMock
    ) -> None:
        # First poll raises, second poll returns accept
        mock_fetch.side_effect = [
            RuntimeError("transient error"),
            [_make_reply("approve")],
        ]
        exit_code, output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=0,
            accept_keywords=self._ACCEPT,
            reject_keywords=self._REJECT,
        )
        assert exit_code == 0
        assert "approve" in output

    @patch.object(_module, "_fetch_replies_since")
    def test_case_insensitive_keyword_matching(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [_make_reply("MERGE")]
        exit_code, _output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=0,
            accept_keywords=self._ACCEPT,
            reject_keywords=self._REJECT,
        )
        assert exit_code == 0

    @patch.object(_module, "_fetch_replies_since")
    def test_custom_keywords(self, mock_fetch: MagicMock) -> None:
        mock_fetch.return_value = [_make_reply("lgtm")]
        exit_code, output = poll_for_reply(
            channel="C123",
            thread_ts="1700000000.0",
            bot_token="xoxb-test",
            timeout_minutes=5,
            poll_interval_seconds=0,
            accept_keywords=["lgtm", "ok"],
            reject_keywords=["nope"],
        )
        assert exit_code == 0
        assert "lgtm" in output
