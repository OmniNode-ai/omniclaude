# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for session resume context formatting."""

import pytest

# session_resume_client lives in plugins/onex/hooks/lib/ which is on sys.path
# via conftest.py's path manipulation.
from session_resume_client import format_resume_context


@pytest.mark.unit
class TestFormatResumeContext:
    def test_formats_active_session(self) -> None:
        snapshot: dict[str, object] = {
            "agent_id": "CAIA",
            "current_ticket": "OMN-7241",
            "git_branch": "jonah/omn-7241-learning-models",
            "working_directory": "/worktrees/OMN-7241/omnibase_infra",  # local-path-ok: test fixture data
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

    def test_minimal_snapshot(self) -> None:
        snapshot: dict[str, object] = {
            "agent_id": "SENTINEL",
            "current_ticket": None,
            "git_branch": "main",
        }
        md = format_resume_context(snapshot, agent_id="SENTINEL")
        assert "## Resumed Session Context (SENTINEL)" in md
        assert "main" in md
