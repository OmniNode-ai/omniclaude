# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for worktree path enforcement in bash_guard.py.

OMN-7018: Verifies that git worktree add commands are blocked when targeting
paths outside the canonical worktree root, and allowed when targeting the
canonical root. Unparseable commands fail closed (blocked).
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import bash_guard  # noqa: E402


def _run_main(hook_input: dict[str, Any]) -> tuple[str, int]:
    """Call ``bash_guard.main()`` with *hook_input* supplied via stdin."""
    raw = json.dumps(hook_input)
    captured = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(raw)),
        patch("sys.stdout", captured),
    ):
        exit_code = bash_guard.main()
    return captured.getvalue().strip(), exit_code


def _bash_input(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.mark.unit
class TestWorktreePathEnforcement:
    """Worktree path enforcement in bash_guard._check_worktree_path."""

    def test_blocks_worktree_outside_canonical(self) -> None:
        """git worktree add to /tmp is blocked."""
        stdout, code = _run_main(
            _bash_input("git worktree add /tmp/bad-worktree -b test-branch")
        )
        assert code == 2
        output = json.loads(stdout)
        assert output["decision"] == "block"
        assert bash_guard.CANONICAL_WORKTREE_ROOT in output["reason"]

    def test_allows_worktree_in_canonical(self) -> None:
        """git worktree add to canonical path is allowed."""
        stdout, code = _run_main(
            _bash_input(
                "git worktree add /Volumes/PRO-G40/Code/omni_worktrees/OMN-1234/repo -b test-branch"  # local-path-ok
            )
        )
        assert code == 0

    def test_blocks_unparseable_worktree_command(self) -> None:
        """git worktree add with no parseable path is blocked (fail closed)."""
        stdout, code = _run_main(_bash_input("git worktree add"))
        assert code == 2
        output = json.loads(stdout)
        assert output["decision"] == "block"
        assert "Could not parse" in output["reason"]

    def test_blocks_worktree_to_home_directory(self) -> None:
        """git worktree add targeting home directory is blocked."""
        stdout, code = _run_main(
            _bash_input("git -C /some/repo worktree add ~/my-worktree -b feat")
        )
        assert code == 2
        output = json.loads(stdout)
        assert output["decision"] == "block"

    def test_non_worktree_git_commands_unaffected(self) -> None:
        """Regular git commands are not affected by worktree enforcement."""
        stdout, code = _run_main(_bash_input("git status"))
        assert code == 0

    def test_blocks_worktree_with_flags_before_path(self) -> None:
        """Flags before path make it unparseable — fail closed."""
        stdout, code = _run_main(
            _bash_input("git worktree add --lock /tmp/locked-tree -b feat")
        )
        assert code == 2
        output = json.loads(stdout)
        assert output["decision"] == "block"

    def test_check_worktree_path_returns_none_for_non_worktree(self) -> None:
        """_check_worktree_path returns None for non-worktree commands."""
        assert bash_guard._check_worktree_path("git status") is None
        assert bash_guard._check_worktree_path("ls -la") is None

    def test_check_worktree_path_allows_canonical(self) -> None:
        """_check_worktree_path returns None for valid canonical path."""
        result = bash_guard._check_worktree_path(
            "git worktree add /Volumes/PRO-G40/Code/omni_worktrees/OMN-99/repo -b feat"  # local-path-ok
        )
        assert result is None

    def test_check_worktree_path_blocks_invalid(self) -> None:
        """_check_worktree_path returns reason for invalid path."""
        result = bash_guard._check_worktree_path("git worktree add /tmp/bad -b feat")
        assert result is not None
        assert "BLOCKED" in result


@pytest.mark.unit
class TestWorktreeFalsePositives:
    """Worktree detection must not false-positive on quoted strings."""

    def test_commit_message_with_worktree_allowed(self) -> None:
        """git commit -m containing 'worktree' must not trigger worktree guard."""
        stdout, code = _run_main(_bash_input('git commit -m "fix worktree pruning"'))
        assert code == 0

    def test_commit_message_with_worktree_add_allowed(self) -> None:
        """git commit -m containing 'worktree add' must not trigger worktree guard."""
        stdout, code = _run_main(
            _bash_input('git commit -m "fix git worktree add path resolution"')
        )
        assert code == 0

    def test_grep_for_worktree_allowed(self) -> None:
        """grep searching for 'worktree' in files must be allowed."""
        stdout, code = _run_main(_bash_input('grep "git worktree add" somefile.sh'))
        assert code == 0

    def test_echo_worktree_allowed(self) -> None:
        """echo containing 'worktree add' must be allowed."""
        stdout, code = _run_main(_bash_input("echo 'git worktree add /some/path'"))
        assert code == 0

    def test_real_worktree_add_still_enforced(self) -> None:
        """Actual git worktree add to non-canonical path is still blocked."""
        stdout, code = _run_main(_bash_input("git worktree add /tmp/bad-tree -b feat"))
        assert code == 2
        output = json.loads(stdout)
        assert output["decision"] == "block"

    def test_real_worktree_add_canonical_still_allowed(self) -> None:
        """Actual git worktree add to canonical path is still allowed."""
        stdout, code = _run_main(
            _bash_input(
                "git worktree add /Volumes/PRO-G40/Code/omni_worktrees/OMN-1234/repo -b feat"  # local-path-ok
            )
        )
        assert code == 0

    def test_is_real_worktree_add_ignores_quoted(self) -> None:
        """_is_real_worktree_add returns False for quoted occurrences."""
        assert not bash_guard._is_real_worktree_add('git commit -m "fix worktree add"')
        assert not bash_guard._is_real_worktree_add("grep 'git worktree add' file.sh")

    def test_is_real_worktree_add_detects_real(self) -> None:
        """_is_real_worktree_add returns True for actual commands."""
        assert bash_guard._is_real_worktree_add("git worktree add /tmp/foo -b bar")
        assert bash_guard._is_real_worktree_add(
            "git -C /some/repo worktree add /tmp/foo"
        )
