# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pre_tool_use_workflow_guard (OMN-6231).

Tests triage-first and ticket-first enforcement:
- Triage-first: epic creation warned without TRIAGE_COMPLETE marker
- Ticket-first: git commit warned without OMN-\\d+ in branch or commit message
- Pass-through: everything else
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from omniclaude.hooks.pre_tool_use_workflow_guard import run_guard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _linear_save_hook(parent_id: str | None = None, title: str = "My Epic") -> str:
    payload: dict = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"title": title},
    }
    if parent_id is not None:
        payload["tool_input"]["parentId"] = parent_id
    return json.dumps(payload)


def _bash_commit_hook(command: str) -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _bash_other_hook(command: str = "ls -la") -> str:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def _write_hook(file_path: str = "/project/file.py", content: str = "pass") -> str:
    return json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
    )


# ---------------------------------------------------------------------------
# Triage-first: epic creation without marker file
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_epic_creation_without_triage_marker_warns(tmp_path: Path) -> None:
    # No marker file in tmp_path
    hook_json = _linear_save_hook()
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 1
    result = json.loads(output)
    assert result["decision"] == "warn"
    assert "triage" in result["reason"].lower() or "TRIAGE" in result["reason"]


@pytest.mark.unit
def test_epic_creation_with_triage_marker_passes(tmp_path: Path) -> None:
    # Write marker file
    state_dir = tmp_path / ".onex_state"
    state_dir.mkdir()
    (state_dir / "triage_complete").touch()

    hook_json = _linear_save_hook()
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_child_issue_creation_skips_triage_check(tmp_path: Path) -> None:
    """Creating a child issue (with parentId) should not trigger triage check."""
    hook_json = _linear_save_hook(parent_id="OMN-6229")
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_update_issue_is_not_intercepted(tmp_path: Path) -> None:
    """mcp__linear-server__update_issue is not intercepted (only save_issue)."""
    hook_json = json.dumps(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {"id": "OMN-6230", "stateId": "abc"},
        }
    )
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Ticket-first: git commit without OMN-\d+ in branch or commit message
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_git_commit_without_ticket_id_warns_when_branch_lacks_id(
    tmp_path: Path,
) -> None:
    hook_json = _bash_commit_hook('git commit -m "fix some stuff"')
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._get_current_branch",
            return_value="main",
        ),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 1
    result = json.loads(output)
    assert result["decision"] == "warn"
    assert "OMN" in result["reason"] or "ticket" in result["reason"].lower()


@pytest.mark.unit
def test_git_commit_with_ticket_id_in_branch_passes(tmp_path: Path) -> None:
    hook_json = _bash_commit_hook('git commit -m "fix something"')
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._get_current_branch",
            return_value="jonah/omn-6231-some-description",
        ),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_git_commit_with_ticket_id_in_message_passes(tmp_path: Path) -> None:
    hook_json = _bash_commit_hook('git commit -m "OMN-1234: implement the thing"')
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._get_current_branch",
            return_value="feature/no-ticket",
        ),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_non_commit_bash_command_passes_through(tmp_path: Path) -> None:
    hook_json = _bash_other_hook("ls -la /project")
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_git_push_not_intercepted(tmp_path: Path) -> None:
    """git push is not a commit — should pass through."""
    hook_json = _bash_other_hook("git push origin main")
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


# ---------------------------------------------------------------------------
# Pass-through: non-intercepted tools
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_tool_is_passed_through(tmp_path: Path) -> None:
    hook_json = _write_hook()
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_invalid_json_fails_open() -> None:
    exit_code, output = run_guard("not-valid-json")
    assert exit_code == 0


@pytest.mark.unit
def test_empty_json_fails_open() -> None:
    exit_code, output = run_guard("{}")
    assert exit_code == 0
