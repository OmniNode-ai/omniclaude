#!/usr/bin/env python3
"""Pre-push validator — runs adaptive lint/format checks before git push.

Detects repo tooling (Python via pyproject.toml, Node via package.json,
or custom via .claude/validation.yaml) and runs appropriate checks on
changed files only. 20s total budget, 10s per command.

Exit codes:
    0 — all checks pass (or no checks applicable)
    2 — validation failed (blocks the push)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

TOTAL_BUDGET_SECONDS = 20
COMMAND_TIMEOUT_SECONDS = 10


def _find_repo_root() -> Path | None:
    """Walk up from cwd to find the repo root (has .git)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".git").exists() or (parent / ".git").is_file():
            return parent
    return None


def _get_changed_files(repo_root: Path) -> list[str]:
    """Get files changed relative to the remote tracking branch."""
    try:
        # Get the upstream tracking branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            # No upstream; diff against HEAD
            upstream = "HEAD"
        else:
            upstream = result.stdout.strip()

        result = subprocess.run(
            ["git", "diff", "--name-only", upstream],
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except (subprocess.TimeoutExpired, Exception):
        pass
    return []


def _run_check(
    cmd: list[str], cwd: Path, label: str, deadline: float
) -> tuple[bool, str]:
    """Run a check command with timeout. Returns (passed, message)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return True, f"  {label}: SKIPPED (budget exceeded)"

    timeout = min(COMMAND_TIMEOUT_SECONDS, remaining)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0:
            return True, f"  {label}: PASS"
        else:
            output = (result.stdout + result.stderr).strip()
            # Truncate long output
            if len(output) > 500:
                output = output[:500] + "\n... (truncated)"
            return False, f"  {label}: FAIL\n{output}"
    except subprocess.TimeoutExpired:
        return True, f"  {label}: SKIPPED (timeout after {timeout:.0f}s)"
    except FileNotFoundError:
        return True, f"  {label}: SKIPPED (command not found)"


def _detect_and_run(
    repo_root: Path, changed_files: list[str], deadline: float
) -> tuple[bool, list[str]]:
    """Detect repo tooling and run appropriate checks."""
    messages: list[str] = []
    all_passed = True

    # Check for custom validation config first
    custom_config = repo_root / ".claude" / "validation.yaml"
    if custom_config.exists():
        try:
            import yaml  # noqa: F811

            with open(custom_config) as f:
                config = yaml.safe_load(f)
            pre_push = config.get("pre_push", {})
            for key in ["lint_command", "format_command"]:
                cmd_template = pre_push.get(key)
                if cmd_template and time.monotonic() < deadline:
                    files_str = " ".join(changed_files) if changed_files else "."
                    cmd_str = cmd_template.replace("{changed_files}", files_str)
                    passed, msg = _run_check(
                        ["bash", "-c", cmd_str],
                        repo_root,
                        key,
                        deadline,
                    )
                    messages.append(msg)
                    if not passed:
                        all_passed = False
            return all_passed, messages
        except Exception:
            pass  # Fall through to auto-detection

    # Filter changed files by type
    py_files = [f for f in changed_files if f.endswith(".py")]
    ts_files = [f for f in changed_files if f.endswith((".ts", ".tsx", ".js", ".jsx"))]

    # Python repo detection
    if (repo_root / "pyproject.toml").exists() and py_files:
        if time.monotonic() < deadline:
            passed, msg = _run_check(
                ["uv", "run", "ruff", "check"] + py_files,
                repo_root,
                "ruff check",
                deadline,
            )
            messages.append(msg)
            if not passed:
                all_passed = False

        if time.monotonic() < deadline:
            passed, msg = _run_check(
                ["uv", "run", "ruff", "format", "--check"] + py_files,
                repo_root,
                "ruff format",
                deadline,
            )
            messages.append(msg)
            if not passed:
                all_passed = False

    # Node/TypeScript repo detection
    if (repo_root / "package.json").exists() and ts_files:
        # Check if lint script exists in package.json
        try:
            with open(repo_root / "package.json") as f:
                pkg = json.load(f)
            if "lint" in pkg.get("scripts", {}):
                # Detect package manager
                if (repo_root / "pnpm-lock.yaml").exists():
                    pm = "pnpm"
                elif (repo_root / "bun.lockb").exists():
                    pm = "bun"
                else:
                    pm = "npm"

                if time.monotonic() < deadline:
                    passed, msg = _run_check(
                        [pm, "run", "lint"],
                        repo_root,
                        f"{pm} run lint",
                        deadline,
                    )
                    messages.append(msg)
                    if not passed:
                        all_passed = False
        except (json.JSONDecodeError, Exception):
            pass

    # Universal: whitespace check
    if time.monotonic() < deadline:
        passed, msg = _run_check(
            ["git", "diff", "--check", "HEAD"],
            repo_root,
            "whitespace check",
            deadline,
        )
        messages.append(msg)
        if not passed:
            all_passed = False

    return all_passed, messages


def main() -> None:
    """Main entry point — reads hook JSON from stdin, runs validation."""
    tool_info = json.loads(sys.stdin.read())

    repo_root = _find_repo_root()
    if repo_root is None:
        # Not in a git repo — pass through
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    deadline = time.monotonic() + TOTAL_BUDGET_SECONDS
    changed_files = _get_changed_files(repo_root)

    if not changed_files:
        # Nothing changed — pass through
        json.dump(tool_info, sys.stdout)
        sys.exit(0)

    all_passed, messages = _detect_and_run(repo_root, changed_files, deadline)

    if all_passed:
        json.dump(tool_info, sys.stdout)
        sys.exit(0)
    else:
        # Block the push
        result = {
            "decision": "block",
            "reason": "Pre-push validation failed:\n" + "\n".join(messages),
        }
        json.dump(result, sys.stdout)
        sys.exit(2)


if __name__ == "__main__":
    main()
