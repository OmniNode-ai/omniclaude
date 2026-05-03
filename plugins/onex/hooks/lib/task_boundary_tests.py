#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Task-boundary test discovery and execution hook.

Fired on PreToolUse(Bash) when the command contains ``git commit`` or
``gh pr create``.  Discovers relevant tests for staged Python files and
runs them with a 120 s budget.  Blocks the tool call on test failure;
fails open on timeout / infrastructure errors.

Exit codes:
    0 — all checks pass (or no tests applicable / infra failure)
    2 — test failures found (blocks the commit/PR)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEBOUNCE_SECONDS = 60
TEST_TIMEOUT_SECONDS = 120

_RE_GIT_COMMIT = re.compile(r"(^|\s|&&|\|\||;)\s*git\s+commit\b")
_RE_GH_PR_CREATE = re.compile(r"(^|\s|&&|\|\||\||;)\s*gh\s+pr\s+create\b")


def _is_trigger_command(command: str) -> bool:
    return bool(_RE_GIT_COMMIT.search(command) or _RE_GH_PR_CREATE.search(command))


def _repo_root_for(cwd: str | None) -> Path | None:
    start = Path(cwd) if cwd else Path.cwd()
    for p in [start, *start.parents]:
        if (p / ".git").exists() or (p / ".git").is_file():
            return p
    return None


def _staged_python_files(repo_root: Path) -> list[str]:
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--", "*.py"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        if r.returncode == 0:
            return [f for f in r.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return []


def _discover_tests(repo_root: Path, changed_files: list[str]) -> list[str]:
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return []

    collected: list[str] = []
    for changed in changed_files:
        stem = Path(changed).stem
        candidates = [
            tests_dir / f"test_{stem}.py",
        ]
        parent = Path(changed).parent
        if str(parent) != ".":
            candidates.append(tests_dir / parent / f"test_{stem}.py")
            candidates.append(tests_dir / "hooks" / f"test_{stem}.py")

        for cand in candidates:
            if cand.is_file() and str(cand) not in collected:
                collected.append(str(cand))

    return collected


def _debounce_key(repo_root: Path) -> str:
    h = hashlib.sha256(str(repo_root).encode()).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), f"onex_task_boundary_last_run_{h}")


def _should_skip_debounce(key: str) -> bool:
    try:
        p = Path(key)
        if not p.exists():
            return False
        mtime = p.stat().st_mtime
        return (time.time() - mtime) < DEBOUNCE_SECONDS
    except OSError:
        return False


def _touch_debounce(key: str) -> None:
    try:
        Path(key).touch()
    except OSError:
        pass


def _run_tests(repo_root: Path, test_files: list[str]) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                *test_files,
                "-q",
                "--tb=short",
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=TEST_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True, "task-boundary-tests: timed out after 120s (failing open)"
    except FileNotFoundError:
        return True, "task-boundary-tests: pytest not found (failing open)"

    if r.returncode == 0:
        return True, ""

    output = (r.stdout + "\n" + r.stderr).strip()
    if len(output) > 2000:
        output = output[:2000] + "\n... (truncated)"
    return False, output


def main() -> None:
    tool_info = json.loads(sys.stdin.read())

    tool_name = tool_info.get("tool_name", "")
    if tool_name != "Bash":
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    command = tool_info.get("tool_input", {}).get("command", "")
    if not _is_trigger_command(command):
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    cwd = tool_info.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    repo_root = _repo_root_for(cwd)
    if repo_root is None:
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    debounce_key = _debounce_key(repo_root)
    if _should_skip_debounce(debounce_key):
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    changed = _staged_python_files(repo_root)
    if not changed:
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    tests = _discover_tests(repo_root, changed)
    if not tests:
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    passed, message = _run_tests(repo_root, tests)
    if passed:
        _touch_debounce(debounce_key)
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    result = {
        "decision": "block",
        "reason": "Task-boundary tests failed:\n" + message,
    }
    json.dump(result, sys.stdout)
    sys.exit(2)


if __name__ == "__main__":
    main()
