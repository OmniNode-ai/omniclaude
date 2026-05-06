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

_HOOKS_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"


def _all_hooks_json_files() -> list[Path]:
    """Return all hooks*.json files in the hooks directory."""
    return sorted(_HOOKS_DIR.glob("hooks*.json"))


def _collect_hook_commands_from(hooks_file: Path) -> list[tuple[str, str, str]]:
    """Return (file_stem, event_name, command) triples for every hook entry in a file."""
    data = json.loads(hooks_file.read_text())
    triples: list[tuple[str, str, str]] = []
    for event_name, hook_groups in data.get("hooks", {}).items():
        for group in hook_groups:
            for hook in group.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd:
                    triples.append((hooks_file.stem, event_name, cmd))
    return triples


def _collect_hook_commands() -> list[tuple[str, str]]:
    """Return (event_name, command) pairs for every hook entry across all hooks*.json files."""
    pairs: list[tuple[str, str]] = []
    for hooks_file in _all_hooks_json_files():
        for _stem, event_name, cmd in _collect_hook_commands_from(hooks_file):
            pairs.append((event_name, cmd))
    return pairs


def _collect_all_hook_commands_with_source() -> list[tuple[str, str, str]]:
    """Return (file_stem, event_name, command) triples across all hooks*.json files."""
    triples: list[tuple[str, str, str]] = []
    for hooks_file in _all_hooks_json_files():
        triples.extend(_collect_hook_commands_from(hooks_file))
    return triples


def _resolve_command(command: str) -> Path:
    """Expand ${CLAUDE_PLUGIN_ROOT} to the canonical plugin root and return the path."""
    plugin_root = str(Path(__file__).parent.parent.parent / "plugins" / "onex")
    resolved = command.replace("${CLAUDE_PLUGIN_ROOT}", plugin_root)
    return Path(resolved)


_ALL_HOOK_COMMANDS_WITH_SOURCE = _collect_all_hook_commands_with_source()


@pytest.mark.parametrize(
    ("file_stem", "event_name", "command"),
    _ALL_HOOK_COMMANDS_WITH_SOURCE,
    ids=[f"{s}::{e}::{c.split('/')[-1]}" for s, e, c in _ALL_HOOK_COMMANDS_WITH_SOURCE],
)
def test_hook_command_exists(file_stem: str, event_name: str, command: str) -> None:
    """Assert the hook command resolves to an existing file (covers all hooks*.json)."""
    path = _resolve_command(command)
    assert path.is_file(), (
        f"Hook command for '{event_name}' in {file_stem}.json does not resolve to a regular file:\n"
        f"  raw command: {command!r}\n"
        f"  resolved:    {path}\n"
        "Update the hooks JSON file or restore the missing script."
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


_ALL_SH_COMMANDS_WITH_SOURCE = [
    (s, e, c) for s, e, c in _ALL_HOOK_COMMANDS_WITH_SOURCE if c.endswith(".sh")
]


@pytest.mark.parametrize(
    ("file_stem", "event_name", "command"),
    _ALL_SH_COMMANDS_WITH_SOURCE,
    ids=[f"{s}::{e}::{c.split('/')[-1]}" for s, e, c in _ALL_SH_COMMANDS_WITH_SOURCE],
)
def test_hook_script_is_executable(
    file_stem: str, event_name: str, command: str
) -> None:
    """Assert .sh hook scripts have the executable bit set (covers all hooks*.json)."""
    path = _resolve_command(command)
    if not path.exists():
        pytest.skip(
            f"Script does not exist (caught by test_hook_command_exists): {path}"
        )
    assert os.access(path, os.X_OK), (
        f"Hook script for '{event_name}' in {file_stem}.json is not executable:\n"
        f"  path: {path}\n"
        "Run: chmod +x <path>"
    )
