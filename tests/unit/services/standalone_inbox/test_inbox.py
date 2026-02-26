# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for the standalone file-based inbox."""

from __future__ import annotations

import json
import time

import pytest

from omniclaude.services.standalone_inbox.inbox import StandaloneInbox


@pytest.fixture
def inbox(tmp_path):
    """Create a StandaloneInbox with a temporary directory."""
    return StandaloneInbox(inbox_dir=tmp_path)


@pytest.mark.unit
class TestStandaloneInbox:
    """Tests for the StandaloneInbox."""

    def test_check_empty_inbox(self, inbox: StandaloneInbox) -> None:
        """Test checking an empty inbox returns no results."""
        results = inbox.check_inbox()
        assert results == []

    def test_check_with_notification(self, inbox: StandaloneInbox, tmp_path) -> None:
        """Test checking inbox with a notification file."""
        payload = {
            "repo": "OmniNode-ai/omniclaude",
            "pr": 42,
            "run_id": 12345,
            "conclusion": "success",
            "timestamp": time.time(),
        }
        inbox_file = tmp_path / "OmniNode-ai_omniclaude_pr42_run12345.json"
        inbox_file.write_text(json.dumps(payload))

        results = inbox.check_inbox()
        assert len(results) == 1
        assert results[0]["pr"] == 42
        assert results[0]["conclusion"] == "success"

    def test_check_with_repo_filter(self, inbox: StandaloneInbox, tmp_path) -> None:
        """Test checking inbox with repo filter."""
        now = time.time()

        # Write two files for different repos
        file1 = tmp_path / "OmniNode-ai_omniclaude_pr42_run1.json"
        file1.write_text(
            json.dumps(
                {
                    "repo": "OmniNode-ai/omniclaude",
                    "pr": 42,
                    "run_id": 1,
                    "conclusion": "success",
                    "timestamp": now,
                }
            )
        )

        file2 = tmp_path / "OmniNode-ai_omnibase_core_pr10_run2.json"
        file2.write_text(
            json.dumps(
                {
                    "repo": "OmniNode-ai/omnibase_core",
                    "pr": 10,
                    "run_id": 2,
                    "conclusion": "failure",
                    "timestamp": now + 1,
                }
            )
        )

        # Filter by repo
        results = inbox.check_inbox(repo="OmniNode-ai/omniclaude")
        assert len(results) == 1
        assert results[0]["repo"] == "OmniNode-ai/omniclaude"

    def test_cursor_prevents_rereading(self, inbox: StandaloneInbox, tmp_path) -> None:
        """Test that cursor prevents re-reading old notifications."""
        payload = {
            "repo": "OmniNode-ai/omniclaude",
            "pr": 42,
            "run_id": 12345,
            "conclusion": "success",
            "timestamp": time.time(),
        }
        inbox_file = tmp_path / "OmniNode-ai_omniclaude_pr42_run12345.json"
        inbox_file.write_text(json.dumps(payload))

        # First check: should return the notification
        results1 = inbox.check_inbox()
        assert len(results1) == 1

        # Second check: cursor updated, should return nothing
        results2 = inbox.check_inbox()
        assert len(results2) == 0

    def test_get_notification_for_run(self, inbox: StandaloneInbox, tmp_path) -> None:
        """Test getting a specific notification by run_id."""
        payload = {
            "repo": "OmniNode-ai/omniclaude",
            "pr": 42,
            "run_id": 12345,
            "conclusion": "success",
            "timestamp": time.time(),
        }
        inbox_file = tmp_path / "OmniNode-ai_omniclaude_pr42_run12345.json"
        inbox_file.write_text(json.dumps(payload))

        result = inbox.get_notification_for_run("OmniNode-ai/omniclaude", 42, 12345)
        assert result is not None
        assert result["conclusion"] == "success"

    def test_get_notification_for_run_missing(self, inbox: StandaloneInbox) -> None:
        """Test getting a notification for a non-existent run."""
        result = inbox.get_notification_for_run("OmniNode-ai/omniclaude", 42, 99999)
        assert result is None
