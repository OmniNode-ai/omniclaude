# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI test: every hook command in hooks.json must resolve to an existing executable.

Gives the model a CI signal to trust over agent claims — verifiers can lie,
CI cannot. Catches both stale paths (scripts deleted without updating hooks.json)
and agent false negatives that claim scripts are missing when they exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_HOOKS_JSON = (
    Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "hooks.json"
)


def _collect_hook_commands() -> list[tuple[str, str]]:
    """Return (event_name, command) pairs for every hook entry."""
    data = json.loads(_HOOKS_JSON.read_text())
    pairs: list[tuple[str, str]] = []
    for event_name, hook_groups in data.get("hooks", {}).items():
        for group in hook_groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    pairs.append((event_name, cmd))
    return pairs


def _resolve_command(command: str) -> Path:
    """Expand ${CLAUDE_PLUGIN_ROOT} to the canonical plugin root and return the path."""
    plugin_root = str(Path(__file__).parent.parent.parent / "plugins" / "onex")
    resolved = command.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root)
    return Path(resolved)


@pytest.mark.parametrize(
    ("event_name", "command"),
    _collect_hook_commands(),
    ids=[f"{e}::{c.split('/')[-1]}" for e, c in _collect_hook_commands()],
)
def test_hook_command_exists(event_name: str, command: str) -> None:
    """Assert the hook command resolves to an existing file."""
    path = _resolve_command(command)
    assert path.is_file(), (
        f"Hook command for '{event_name}' does not resolve to a regular file:\n"
        f"  raw command: {command!r}\n"
        f"  resolved:    {path}\n"
        "Update hooks.json or restore the missing script."
    )


def _collect_pretooluse_matchers() -> list[tuple[str, str]]:
    """Return (matcher, command) pairs for all PreToolUse hooks that have a matcher."""
    data = json.loads(_HOOKS_JSON.read_text())
    pairs: list[tuple[str, str]] = []
    for group in data.get("hooks", {}).get("PreToolUse", []):
        matcher = group.get("matcher")
        if not matcher:
            continue
        for hook in group.get("hooks", []):
            cmd = hook.get("command", "")
            if cmd:
                pairs.append((matcher, cmd))
    return pairs


def test_tracker_save_issue_covered_by_workflow_guard_matcher() -> None:
    """tracker.save_issue must be covered by the workflow guard PreToolUse matcher.

    The Python guard handles both mcp__linear-server__save_issue and tracker.save_issue,
    but the shell entry-gate (hooks.json matcher) must also match tracker.save_issue
    or the guard is never invoked for migrated tracker.* calls.
    """
    import re

    guard_script = "pre_tool_use_workflow_guard.sh"
    for matcher, command in _collect_pretooluse_matchers():
        if command.endswith(guard_script):
            assert re.match(matcher, "tracker.save_issue"), (
                f"hooks.json PreToolUse matcher for {guard_script!r} does not match "
                f"'tracker.save_issue'.\n"
                f"  Current matcher: {matcher!r}\n"
                "Extend the matcher to include tracker\\.save_issue so the shell "
                "entry-gate forwards tracker.* epic creation calls to the guard."
            )
            return
    pytest.fail(
        f"No PreToolUse hook entry found for {guard_script!r} in hooks.json. "
        "The workflow guard must be registered."
    )


@pytest.mark.parametrize(
    ("event_name", "command"),
    [(e, c) for e, c in _collect_hook_commands() if c.endswith(".sh")],
    ids=[
        f"{e}::{c.split('/')[-1]}"
        for e, c in _collect_hook_commands()
        if c.endswith(".sh")
    ],
)
def test_hook_script_is_executable(event_name: str, command: str) -> None:
    """Assert .sh hook scripts have the executable bit set."""
    path = _resolve_command(command)
    if not path.exists():
        pytest.skip(
            f"Script does not exist (caught by test_hook_command_exists): {path}"
        )
    assert os.access(path, os.X_OK), (
        f"Hook script for '{event_name}' is not executable:\n"
        f"  path: {path}\n"
        "Run: chmod +x <path>"
    )
