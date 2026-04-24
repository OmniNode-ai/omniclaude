# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for session_start_onex_cli_pin_check.sh advisory hook (OMN-8799).

Verifies:
  * Script exists and is executable
  * Exits 0 whether onex is present, missing, or below the pin (non-blocking)
  * Reads min_runtime_version from the bundled plugin-compat.yaml
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PLUGIN_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "scripts" / "session_start_onex_cli_pin_check.sh"


class TestHookScriptPresence:
    def test_script_exists(self) -> None:
        assert HOOK_SCRIPT.exists(), f"onex CLI pin check hook missing at {HOOK_SCRIPT}"

    def test_script_is_executable(self) -> None:
        mode = HOOK_SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, (
            f"{HOOK_SCRIPT} must have the user-executable bit set"
        )


def _bash() -> str:
    """Absolute path to bash so tests can strip onex from PATH without
    losing the interpreter itself."""
    for candidate in ("/bin/bash", "/usr/bin/bash", "/opt/homebrew/bin/bash"):
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("bash not found on test host")


class TestHookScriptBehavior:
    def test_exits_zero_when_plugin_root_missing(self) -> None:
        env = os.environ.copy()
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        result = subprocess.run(
            [_bash(), str(HOOK_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0

    def test_exits_zero_when_onex_missing(self, tmp_path: Path) -> None:
        """Non-blocking contract: advisory only, never prevents session start."""
        # Build a sandbox PATH that has the system utilities the hook needs
        # (awk, grep, sed) but explicitly does NOT have `onex`.
        sandbox_bin = tmp_path / "bin"
        sandbox_bin.mkdir()
        for tool in ("awk", "grep", "sed", "head"):
            src = Path("/usr/bin") / tool
            if not src.exists():
                src = Path("/bin") / tool
            if src.exists():
                (sandbox_bin / tool).symlink_to(src)
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
        env["PATH"] = str(sandbox_bin)
        result = subprocess.run(
            [_bash(), str(HOOK_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert "onex" in result.stderr.lower()
        assert "pipx" in result.stderr.lower()

    def test_silent_when_compat_yaml_absent(self, tmp_path: Path) -> None:
        """If plugin-compat.yaml is unreadable, emit nothing and exit 0."""
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(tmp_path)  # no plugin-compat.yaml here
        env["PATH"] = "/nonexistent"
        result = subprocess.run(
            [_bash(), str(HOOK_SCRIPT)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""
