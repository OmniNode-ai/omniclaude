# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for session resume context formatting."""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"),
)

from session_resume_client import (  # noqa: E402
    format_resume_context,
)


@pytest.mark.unit
class TestFormatResumeContext:
    def test_formats_active_session(self) -> None:
        snapshot: dict[str, object] = {
            "agent_id": "CAIA",
            "current_ticket": "OMN-7241",
            "git_branch": "jonah/omn-7241-learning-models",
            "working_directory": "/Volumes/PRO-G40/Code/omni_worktrees/OMN-7241/omnibase_infra",  # local-path-ok
            "files_touched": ["src/models/agent_learning.py", "tests/test_agent.py"],
            "errors_hit": ["ImportError: cannot import 'foo'"],
            "last_tool_name": "Bash",
            "last_tool_success": False,
            "last_tool_summary": "pytest failed: 1 error",
            "session_outcome": None,
            "session_started_at": "2026-04-02T10:00:00Z",
        }
        md = format_resume_context(snapshot, agent_id="CAIA")
        assert "## Resumed Session Context (CAIA)" in md
        assert "OMN-7241" in md
        assert "learning-models" in md
        assert "ImportError" in md

    def test_empty_snapshot_returns_empty(self) -> None:
        assert format_resume_context(None, agent_id="CAIA") == ""

    def test_completed_session(self) -> None:
        snapshot: dict[str, object] = {
            "agent_id": "CAIA",
            "current_ticket": "OMN-7241",
            "git_branch": "jonah/omn-7241-learning-models",
            "session_outcome": "success",
            "files_touched": ["src/models/agent_learning.py"],
            "errors_hit": [],
            "last_tool_name": "Bash",
            "last_tool_success": True,
            "session_started_at": "2026-04-02T10:00:00Z",
            "session_ended_at": "2026-04-02T11:30:00Z",
        }
        md = format_resume_context(snapshot, agent_id="CAIA")
        assert "success" in md.lower()
