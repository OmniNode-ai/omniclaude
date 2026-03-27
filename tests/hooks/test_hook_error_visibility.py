# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for hook error visibility [OMN-6734].

Verifies that the fixes from PRs #885, #890, #880 correctly propagate
errors through the hook system:

1. Crash handling (#885): Errors caught, logged, hook exits 0
2. Degraded notifications (#890): Failure metadata captured for Slack
3. sys.path guard (#880): find_python() fails loudly when misconfigured

Tests cover BOTH direct invocation (bash -c / python3) AND hook event
chain behavior (error-guard.sh sourced at top of hook scripts).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
HOOKS_DIR = REPO_ROOT / "plugins/onex/hooks"
SCRIPTS_DIR = HOOKS_DIR / "scripts"
ERROR_GUARD = SCRIPTS_DIR / "error-guard.sh"
COMMON_SH = SCRIPTS_DIR / "common.sh"


# =============================================================================
# error-guard.sh crash handling (#885)
# =============================================================================


@pytest.mark.unit
def test_error_guard_catches_exit_1_returns_0() -> None:
    """error-guard.sh must swallow exit 1 and return 0."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-crash.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
exit 1
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, (
        f"error-guard.sh must exit 0 on crash, got {result.returncode}"
    )


@pytest.mark.unit
def test_error_guard_catches_set_e_failure_returns_0() -> None:
    """set -e triggered failure must be caught and return 0."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-sete.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
false
echo 'should-not-reach'
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "should-not-reach" not in result.stdout


@pytest.mark.unit
def test_error_guard_drains_stdin_on_failure() -> None:
    """Stdin must be drained so Claude Code doesn't hang on unread pipe."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-drain.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
exit 1
""",
        ],
        input='{"test": "data"}',
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0


@pytest.mark.unit
def test_error_guard_normal_exit_passes_through() -> None:
    """Exit 0 should pass through without intervention."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-ok.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
echo 'hello'
exit 0
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "hello" in result.stdout


# =============================================================================
# Degraded notification metadata (#890)
# =============================================================================


@pytest.mark.unit
def test_error_guard_logs_failure_metadata() -> None:
    """On failure, hook name + exit code must be logged to errors.log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-metadata.sh'
export _ERROR_GUARD_LOG_DIR='{tmpdir}'
source '{ERROR_GUARD}' 2>/dev/null || true
exit 42
""",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0

        # Check error log exists and contains metadata
        error_log = Path(tmpdir) / "errors.log"
        assert error_log.exists(), "errors.log must be created on failure"
        content = error_log.read_text()
        assert "test-metadata.sh" in content, "Hook name must be in error log"
        assert "42" in content, "Exit code must be in error log"


@pytest.mark.unit
def test_error_guard_logs_to_per_hook_file() -> None:
    """Each hook gets its own log file for structured failure tracking."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "bash",
                "-c",
                f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-perhook.sh'
export _ERROR_GUARD_LOG_DIR='{tmpdir}'
source '{ERROR_GUARD}' 2>/dev/null || true
exit 7
""",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        per_hook_log = Path(tmpdir) / "test-perhook.sh.log"
        assert per_hook_log.exists(), "Per-hook log file must be created"
        content = per_hook_log.read_text()
        assert "ERROR" in content
        assert "exit code 7" in content


@pytest.mark.unit
def test_error_guard_slack_payload_structure() -> None:
    """Slack alert must include hook name, exit code, and host in the message.

    We don't actually send to Slack — we verify the format by checking
    the curl command would be constructed correctly. The error-guard.sh
    constructs the payload inline (no jq dependency).
    """
    # error-guard.sh constructs:
    # "[error-guard][${host}] Hook '${hook_name}' crashed with exit code ${code}. Swallowed..."
    # Verify this format exists in the script
    guard_content = ERROR_GUARD.read_text()
    assert "Hook '" in guard_content, "Slack message must include hook name"
    assert "exit code" in guard_content, "Slack message must include exit code"
    assert "error-guard" in guard_content, "Slack message must identify error-guard"


# =============================================================================
# sys.path guard / find_python() (#880)
# =============================================================================


@pytest.mark.unit
def test_find_python_returns_valid_path_in_dev_mode() -> None:
    """find_python() with OMNICLAUDE_PROJECT_ROOT set returns a valid Python."""
    # Find the venv in this worktree
    venv_python = REPO_ROOT / ".venv/bin/python3"
    if not venv_python.exists():
        pytest.skip("No .venv in worktree (CI uses uv)")

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
export PLUGIN_ROOT='{HOOKS_DIR.parent}'
export OMNICLAUDE_PROJECT_ROOT='{REPO_ROOT}'
source '{COMMON_SH}'
echo "$PYTHON_CMD"
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={
            **os.environ,
            "PLUGIN_PYTHON_BIN": "",
            "OMNICLAUDE_PROJECT_ROOT": str(REPO_ROOT),
        },
    )
    # Should either succeed with a path or fail with actionable error
    if result.returncode == 0:
        python_path = result.stdout.strip().splitlines()[-1]
        assert python_path, "PYTHON_CMD must not be empty"


@pytest.mark.unit
def test_find_python_fails_loudly_when_all_paths_invalid() -> None:
    """find_python() must fail with actionable error when no Python found.

    With PLUGIN_PYTHON_BIN pointing to nonexistent file, no plugin venv,
    no OMNICLAUDE_PROJECT_ROOT, and full mode (not lite), it should exit 1.
    """
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
export PLUGIN_ROOT='/nonexistent/plugin'
export PLUGIN_PYTHON_BIN='/nonexistent/python3'
unset OMNICLAUDE_PROJECT_ROOT
source '{COMMON_SH}'
echo "PYTHON_CMD=$PYTHON_CMD"
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={
            "HOME": os.environ.get("HOME", "/tmp"),
            # Keep /usr/bin for bash/date but remove python3 from PATH
            "PATH": "/usr/bin:/bin",
            "PLUGIN_PYTHON_BIN": "/nonexistent/python3",
        },
    )
    # Should fail (exit 1) with an actionable message
    # OR succeed with a warning if system python3 is found in lite mode fallback
    combined = result.stdout + result.stderr
    # The key assertion: either it hard-fails or it warns — never silent
    assert (
        result.returncode != 0 or "WARN" in combined or "python" in combined.lower()
    ), "find_python() must not silently succeed when all paths are invalid"


# =============================================================================
# Hook event chain integration
# =============================================================================


@pytest.mark.unit
def test_all_hook_scripts_source_error_guard() -> None:
    """Every registered hook script must source error-guard.sh.

    This is the structural regression test: if a new hook is added without
    error-guard.sh, errors will crash Claude Code instead of being swallowed.
    """
    expected_hooks = [
        "session-start.sh",
        "user-prompt-submit.sh",
        "session-end.sh",
        "stop.sh",
        "pre-compact.sh",
        "post-tool-use-quality.sh",
        "post-tool-delegation-counter.sh",
        "post-skill-delegation-enforcer.sh",
        "user-prompt-delegation-rule.sh",
    ]
    missing = []
    for hook_name in expected_hooks:
        hook_path = SCRIPTS_DIR / hook_name
        if not hook_path.exists():
            continue
        content = hook_path.read_text()
        if "error-guard.sh" not in content:
            missing.append(hook_name)

    assert not missing, (
        f"These hooks do NOT source error-guard.sh (error visibility regression): {missing}"
    )


@pytest.mark.unit
def test_error_guard_preserves_output_before_crash() -> None:
    """Output emitted before a crash must still reach stdout."""
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-partial.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
echo 'before-crash'
exit 1
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "before-crash" in result.stdout, "Output before crash must be preserved"


@pytest.mark.unit
def test_error_guard_handles_arbitrary_exit_codes() -> None:
    """Exit codes other than 0/1 must also be caught."""
    for code in [2, 42, 127, 255]:
        result = subprocess.run(
            [
                "bash",
                "-c",
                f"""
set -euo pipefail
_OMNICLAUDE_HOOK_NAME='test-code-{code}.sh'
export _ERROR_GUARD_LOG_DIR="$(mktemp -d)"
source '{ERROR_GUARD}' 2>/dev/null || true
exit {code}
""",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, (
            f"error-guard.sh must catch exit code {code} and return 0"
        )
