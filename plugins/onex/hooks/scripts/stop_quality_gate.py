#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Stop-phase changed-file quality gate.

Runs fast checks only for Python files changed relative to HEAD. Tool timeouts
fail open so Stop remains bounded; actual lint/type/test failures block.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

TOTAL_TIMEOUT_SECONDS = 13.0
RUFF_TIMEOUT_SECONDS = 3.0
MYPY_TIMEOUT_SECONDS = 8.0
PYTEST_TIMEOUT_SECONDS = 5.0
MAX_TEST_FILES = 3


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    returncode: int
    output: str


def _run_git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=2,
        check=False,
    )


def _repo_root(cwd: Path) -> Path | None:
    inside = _run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    root = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if root.returncode != 0:
        return None
    return Path(root.stdout.strip())


def _changed_files(repo_root: Path) -> list[Path]:
    paths: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"], ["diff", "--cached", "--name-only"]):
        result = _run_git(args, repo_root)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            clean = line.strip()
            if clean:
                paths.add(clean)

    return [
        Path(path)
        for path in sorted(paths)
        if path.endswith(".py")
        and (path.startswith("src/") or path.startswith("tests/"))
    ]


def _affected_test_files(changed_files: Sequence[Path], repo_root: Path) -> list[Path]:
    test_files: list[Path] = []
    seen: set[Path] = set()

    for path in changed_files:
        if str(path).startswith("tests/"):
            candidate = path
        elif str(path).startswith("src/"):
            candidate = Path("tests") / f"test_{path.stem}.py"
        else:
            continue

        if candidate in seen:
            continue
        if (repo_root / candidate).is_file():
            seen.add(candidate)
            test_files.append(candidate)
        if len(test_files) >= MAX_TEST_FILES:
            break

    return test_files


def _remaining(started_at: float) -> float:
    return TOTAL_TIMEOUT_SECONDS - (time.monotonic() - started_at)


def _run_check(
    name: str,
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    started_at: float,
) -> CommandResult | None:
    budget = min(timeout, max(0.1, _remaining(started_at)))
    if budget <= 0.1:
        return None
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=budget,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None

    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return CommandResult(
        name=name,
        command=command,
        returncode=result.returncode,
        output=output,
    )


def run_gate(project_root: Path) -> tuple[int, dict[str, object]]:
    started_at = time.monotonic()
    root = _repo_root(project_root)
    if root is None:
        return 0, {"status": "skipped", "reason": "not in git worktree"}

    changed = _changed_files(root)
    if not changed:
        return 0, {"status": "passed", "reason": "no changed Python files"}

    failures: list[CommandResult] = []

    ruff = _run_check(
        "ruff",
        ["uv", "run", "ruff", "check", *map(str, changed)],
        cwd=root,
        timeout=RUFF_TIMEOUT_SECONDS,
        started_at=started_at,
    )
    if ruff is not None and ruff.returncode != 0:
        failures.append(ruff)

    if _remaining(started_at) > 0.1:
        mypy = _run_check(
            "mypy",
            ["uv", "run", "mypy", "--strict", *map(str, changed)],
            cwd=root,
            timeout=MYPY_TIMEOUT_SECONDS,
            started_at=started_at,
        )
        if mypy is not None and mypy.returncode != 0:
            failures.append(mypy)

    for test_file in _affected_test_files(changed, root):
        if _remaining(started_at) <= 0.1:
            break
        pytest = _run_check(
            "pytest",
            ["uv", "run", "pytest", "-m", "unit", str(test_file)],
            cwd=root,
            timeout=PYTEST_TIMEOUT_SECONDS,
            started_at=started_at,
        )
        if pytest is not None and pytest.returncode != 0:
            failures.append(pytest)

    if failures:
        summary = "; ".join(
            f"{failure.name} exited {failure.returncode}" for failure in failures
        )
        details = "\n\n".join(
            f"$ {' '.join(failure.command)}\n{failure.output}".strip()
            for failure in failures
        )
        return 2, {
            "decision": "block",
            "reason": f"Stop quality gate failed: {summary}",
            "details": details[:4000],
        }

    return 0, {
        "status": "passed",
        "checked_files": [str(path) for path in changed],
        "elapsed_ms": int((time.monotonic() - started_at) * 1000),
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
        help="Repository root or path inside the repository.",
    )
    args = parser.parse_args(argv)

    code, payload = run_gate(Path(args.project_root).resolve())
    _emit(payload)
    return code


if __name__ == "__main__":
    sys.exit(main())
