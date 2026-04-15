# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pre_tool_use_workflow_guard (OMN-6231, OMN-7810).

Tests triage-first, ticket-first, and canonical clone write protection:
- Triage-first: epic creation warned without TRIAGE_COMPLETE marker
- Ticket-first: git commit warned without OMN-\\d+ in branch or commit message
- Write protection: Edit/Write to omni_home canonical clones blocked (OMN-7810)
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


def _tracker_save_hook(parent_id: str | None = None, title: str = "My Epic") -> str:
    """Migrated tracker.* equivalent of _linear_save_hook."""
    payload: dict = {
        "tool_name": "tracker.save_issue",
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


def _edit_hook(
    file_path: str = "/project/file.py",
    old_string: str = "old",
    new_string: str = "new",
) -> str:
    return json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": old_string,
                "new_string": new_string,
            },
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
def test_tracker_save_issue_without_triage_marker_warns(tmp_path: Path) -> None:
    """tracker.save_issue (migrated API) triggers triage-first check identically."""
    hook_json = _tracker_save_hook()
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 1
    result = json.loads(output)
    assert result["decision"] == "warn"


@pytest.mark.unit
def test_tracker_save_issue_with_triage_marker_passes(tmp_path: Path) -> None:
    """tracker.save_issue passes when triage marker is present."""
    state_dir = tmp_path / ".onex_state"
    state_dir.mkdir()
    (state_dir / "triage_complete").touch()

    hook_json = _tracker_save_hook()
    with patch(
        "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
        return_value=tmp_path,
    ):
        exit_code, _ = run_guard(hook_json)

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
def test_write_tool_passed_through_without_omni_home(tmp_path: Path) -> None:
    """Write to arbitrary path passes when OMNI_HOME is not set."""
    hook_json = _write_hook()
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {}, clear=False),
    ):
        # Ensure OMNI_HOME is not set
        import os

        os.environ.pop("OMNI_HOME", None)
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


# ---------------------------------------------------------------------------
# Canonical clone write protection (OMN-7810)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_edit_to_canonical_clone_is_blocked(tmp_path: Path) -> None:
    """Edit targeting omni_home/omnimarket/src/... should be hard-blocked."""
    omni_home = tmp_path / "omni_home"
    omni_home.mkdir()
    (omni_home / "omnimarket" / "src").mkdir(parents=True)

    file_path = str(omni_home / "omnimarket" / "src" / "handler.py")
    hook_json = _edit_hook(file_path=file_path)
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {"OMNI_HOME": str(omni_home)}),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"
    assert (
        "canonical clone" in result["reason"].lower()
        or "worktree" in result["reason"].lower()
    )


@pytest.mark.unit
def test_write_to_canonical_clone_is_blocked(tmp_path: Path) -> None:
    """Write targeting omni_home/omniclaude/anything should be hard-blocked."""
    omni_home = tmp_path / "omni_home"
    omni_home.mkdir()
    (omni_home / "omniclaude").mkdir()

    file_path = str(omni_home / "omniclaude" / "new_file.py")
    hook_json = _write_hook(file_path=file_path)
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {"OMNI_HOME": str(omni_home)}),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"


@pytest.mark.unit
def test_edit_in_worktree_is_allowed(tmp_path: Path) -> None:
    """Edit targeting omni_home/worktrees/OMN-1234/repo/src/... should be allowed."""
    omni_home = tmp_path / "omni_home"
    wt = omni_home / "worktrees" / "OMN-1234" / "omnimarket" / "src"
    wt.mkdir(parents=True)

    file_path = str(wt / "handler.py")
    hook_json = _edit_hook(file_path=file_path)
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {"OMNI_HOME": str(omni_home)}),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_edit_outside_omni_home_is_allowed(tmp_path: Path) -> None:
    """Edit to a path completely outside omni_home should be allowed."""
    omni_home = tmp_path / "omni_home"
    omni_home.mkdir()

    file_path = "/some/other/project/file.py"
    hook_json = _edit_hook(file_path=file_path)
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {"OMNI_HOME": str(omni_home)}),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_edit_to_omni_home_top_level_is_allowed(tmp_path: Path) -> None:
    """Edit to omni_home/docs/plan.md (not a known repo) should be allowed."""
    omni_home = tmp_path / "omni_home"
    (omni_home / "docs").mkdir(parents=True)

    file_path = str(omni_home / "docs" / "plan.md")
    hook_json = _edit_hook(file_path=file_path)
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {"OMNI_HOME": str(omni_home)}),
    ):
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0


@pytest.mark.unit
def test_write_protection_without_omni_home_env_allows(tmp_path: Path) -> None:
    """When OMNI_HOME is unset, write protection is skipped."""
    hook_json = _edit_hook(file_path="/fake/omnimarket/src/handler.py")
    with (
        patch(
            "omniclaude.hooks.pre_tool_use_workflow_guard._resolve_project_root",
            return_value=tmp_path,
        ),
        patch.dict("os.environ", {}, clear=False),
    ):
        import os

        os.environ.pop("OMNI_HOME", None)
        exit_code, output = run_guard(hook_json)

    assert exit_code == 0
