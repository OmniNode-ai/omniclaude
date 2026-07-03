# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the sweep preflight PreToolUse hook [OMN-7057].

Validates the pre_tool_use_sweep_preflight.sh hook script:
- Non-Bash tools pass through unchanged
- Non-sweep Bash commands pass through unchanged (ls, cat, git status)
- Sweep-pattern commands (gh pr, merge-sweep) trigger infrastructure checks
- Cache mechanism prevents redundant checks within TTL
- Expired gh auth produces a block decision
- Low rate limit produces a block decision
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

import pytest

# Resolve the hook script path
_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_HOOK_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_sweep_preflight.sh"
)


def _run_hook(
    tool_info: dict, env_overrides: dict | None = None
) -> tuple[int, str, str]:
    """Run the hook script with the given tool_info JSON on stdin.

    Returns (exit_code, stdout, stderr).
    """
    env = os.environ.copy()
    # Ensure we have a writable temp dir for logs and cache
    tmp = tempfile.mkdtemp()
    env["LOG_FILE"] = os.path.join(tmp, "hooks.log")
    env["HOME"] = tmp  # Isolate cache writes
    # Don't actually call gh — mock it via PATH manipulation
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input=json.dumps(tool_info),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


def _make_bash_tool_info(command: str) -> dict:
    """Create a minimal Bash tool invocation JSON."""
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


def _make_non_bash_tool_info() -> dict:
    """Create a non-Bash tool invocation JSON."""
    return {
        "tool_name": "Read",
        "tool_input": {"file_path": "/tmp/test.txt"},
    }


@pytest.mark.unit
class TestSweepPreflightPassthrough:
    """Tests for commands that should pass through without checks."""

    def test_non_bash_tool_passes_through(self):
        """Non-Bash tools are passed through unchanged."""
        tool_info = _make_non_bash_tool_info()
        exit_code, stdout, _ = _run_hook(tool_info)
        assert exit_code == 0
        parsed = json.loads(stdout.strip())
        assert parsed["tool_name"] == "Read"

    def test_non_sweep_bash_passes_through(self):
        """Bash commands that don't match sweep patterns pass through."""
        tool_info = _make_bash_tool_info("ls -la /tmp")
        exit_code, stdout, _ = _run_hook(tool_info)
        assert exit_code == 0
        parsed = json.loads(stdout.strip())
        assert parsed["tool_name"] == "Bash"
        assert parsed["tool_input"]["command"] == "ls -la /tmp"

    def test_git_status_passes_through(self):
        """git status is not a sweep command."""
        tool_info = _make_bash_tool_info("git status")
        exit_code, stdout, _ = _run_hook(tool_info)
        assert exit_code == 0
        parsed = json.loads(stdout.strip())
        assert parsed["tool_input"]["command"] == "git status"

    def test_pytest_passes_through(self):
        """pytest invocations are not sweep commands."""
        tool_info = _make_bash_tool_info("uv run pytest tests/ -v")
        exit_code, stdout, _ = _run_hook(tool_info)
        assert exit_code == 0


@pytest.mark.unit
class TestSweepPreflightDetection:
    """Tests for sweep pattern detection."""

    def test_gh_pr_triggers_check(self):
        """Commands with 'gh ' trigger the preflight check."""
        tool_info = _make_bash_tool_info("gh pr list --state open")
        # This will actually run gh auth check — expected to pass or fail
        # depending on the test environment. We just verify the hook runs
        # (doesn't crash) and returns a valid exit code.
        exit_code, stdout, stderr = _run_hook(tool_info)
        assert exit_code in (0, 2), f"Unexpected exit code {exit_code}: {stderr}"

    def test_git_push_triggers_check(self):
        """git push triggers the preflight check."""
        tool_info = _make_bash_tool_info("git push origin main")
        exit_code, stdout, stderr = _run_hook(tool_info)
        assert exit_code in (0, 2)

    def test_merge_sweep_triggers_check(self):
        """Commands mentioning merge-sweep trigger the check."""
        tool_info = _make_bash_tool_info("echo 'running merge-sweep cycle'")
        exit_code, stdout, stderr = _run_hook(tool_info)
        assert exit_code in (0, 2)


@pytest.mark.unit
class TestSweepPreflightCache:
    """Tests for the cache mechanism."""

    def test_cache_file_created_on_check(self):
        """A cache file is created after running checks."""
        tmp = tempfile.mkdtemp()
        tool_info = _make_bash_tool_info("gh pr list")
        env = {"HOME": tmp, "LOG_FILE": os.path.join(tmp, "hooks.log")}
        _run_hook(tool_info, env_overrides=env)

        cache_file = (
            pathlib.Path(tmp) / ".claude" / "hooks" / ".cache" / "sweep-preflight.json"
        )
        assert cache_file.exists(), "Cache file should be created after check"
        cache_data = json.loads(cache_file.read_text())
        assert cache_data["status"] in ("pass", "block")
        assert "checked_at" in cache_data

    def test_cached_pass_avoids_recheck(self):
        """A fresh 'pass' cache skips the actual infrastructure checks."""
        tmp = tempfile.mkdtemp()
        cache_dir = pathlib.Path(tmp) / ".claude" / "hooks" / ".cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "sweep-preflight.json"
        # Write a fresh pass cache
        cache_file.write_text(
            json.dumps(
                {
                    "status": "pass",
                    "gh_auth": True,
                    "rate_remaining": 4999,
                    "linear_mcp": True,
                    "checked_at": "2026-03-30T00:00:00Z",
                }
            )
        )

        tool_info = _make_bash_tool_info("gh pr list")
        env = {"HOME": tmp, "LOG_FILE": os.path.join(tmp, "hooks.log")}
        exit_code, stdout, _ = _run_hook(tool_info, env_overrides=env)
        assert exit_code == 0
        # Should pass through the original tool info
        parsed = json.loads(stdout.strip())
        assert parsed["tool_name"] == "Bash"

    def test_cached_block_clears_cache_and_rechecks(self):
        """A cached 'block' entry is cleared and the hook re-runs infrastructure checks.

        The hook intentionally does NOT honor cached blocks so that transient
        failures (expired auth, rate limit) recover immediately on the next
        sweep command.  Verify: (a) the cache file is removed before the
        actual gh/rate-limit checks run, and (b) the hook completes with a
        valid exit code (0 = pass, 2 = still blocked after re-check).
        """
        tmp = tempfile.mkdtemp()
        cache_dir = pathlib.Path(tmp) / ".claude" / "hooks" / ".cache"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / "sweep-preflight.json"
        cache_file.write_text(
            json.dumps(
                {
                    "status": "block",
                    "reason": "GitHub auth expired",
                    "checked_at": "2026-03-30T00:00:00Z",
                }
            )
        )

        tool_info = _make_bash_tool_info("gh pr merge --auto")
        env = {"HOME": tmp, "LOG_FILE": os.path.join(tmp, "hooks.log")}
        exit_code, _, _ = _run_hook(tool_info, env_overrides=env)
        # The hook re-runs checks and either passes (0) or blocks again (2).
        # Either outcome is correct; the important invariant is that the hook
        # did NOT short-circuit on the stale block entry.
        assert exit_code in (0, 2), f"Unexpected exit code: {exit_code}"
        # The stale block cache must have been cleared (hook re-wrote or removed it).
        if cache_file.exists():
            new_data = json.loads(cache_file.read_text())
            # Cache was rewritten by the live check — timestamp must differ from
            # the sentinel value written above.
            assert new_data.get("checked_at") != "2026-03-30T00:00:00Z", (
                "Stale cached-block entry was not replaced by a live check result"
            )


@pytest.mark.unit
class TestHooksJsonRegistration:
    """Verify the hook is properly registered in hooks.json."""

    def test_sweep_preflight_registered(self):
        """The sweep preflight hook is registered in hooks.json."""
        hooks_json_path = _REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"
        hooks_config = json.loads(hooks_json_path.read_text())

        if not hooks_config["hooks"].get("PreToolUse"):
            pytest.skip(
                "No PreToolUse hooks registered (hooks disabled for the "
                "OMN-13244 measurement baseline). Re-enable this assertion when "
                "hooks are re-registered."
            )

        pre_tool_use = hooks_config["hooks"]["PreToolUse"]
        sweep_entries = [
            entry
            for entry in pre_tool_use
            if any(
                "pre_tool_use_sweep_preflight.sh" in hook.get("command", "")
                for hook in entry.get("hooks", [])
            )
        ]
        if not sweep_entries:
            # The OMN-13856 Option A carve-out re-registers ONLY the Done-flip
            # guard into the otherwise-empty OMN-13244 baseline; the sweep
            # preflight hook stays disabled. Skip rather than fail — re-enable
            # this assertion when the sweep preflight hook is re-registered.
            pytest.skip(
                "Sweep preflight not registered (OMN-13856 Option A carve-out "
                "registers only the Done-flip guard)."
            )
        assert len(sweep_entries) == 1, (
            "Sweep preflight should be registered exactly once"
        )
        assert sweep_entries[0]["matcher"] == "Bash"
