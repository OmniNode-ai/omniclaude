# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegation hook routes on a Mac with no GNU ``timeout`` (OMN-23413).

Failure mode: macOS ships no ``timeout`` (it comes from GNU coreutils). The hook
ran its router as ``timeout 5 ...``, so on a customer Mac without coreutils the
router never started (exit 127) and every Agent call passed through unrouted,
with only a WARN line to show for it. Claude Code delegation looked switched on
and did nothing.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]
_PLUGIN = _REPO / "plugins" / "onex"
_HOOK = "hooks/scripts/pre_tool_use_delegation.sh"
_AGENT_CALL = {
    "session_id": "no-timeout-test",
    "hook_event_name": "PreToolUse",
    "tool_name": "Agent",
    "tool_input": {
        "subagent_type": "general-purpose",
        "description": "stub",
        "prompt": "stub",
    },
}


def _plugin_with_stub_runner(tmp_path: Path) -> Path:
    """The real plugin tree with a router that only answers DELEGATED."""
    plugin = tmp_path / "plugin" / "onex"
    shutil.copytree(_PLUGIN / "hooks", plugin / "hooks", symlinks=True)
    shutil.copytree(_PLUGIN / "lib", plugin / "lib", symlinks=True)
    (plugin / "hooks" / "lib" / "delegation_hook_runner.py").write_text(
        "import sys\nsys.stdin.read()\nprint('DELEGATED: stub routed to test-model')\n"
    )
    return plugin


def _bin_without_timeout(tmp_path: Path) -> Path:
    """Only jq is added; neither timeout nor gtimeout is reachable."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required by the hook")
    (bin_dir / "jq").symlink_to(jq)
    return bin_dir


def test_hook_delegates_when_no_timeout_command_exists(tmp_path: Path) -> None:
    plugin = _plugin_with_stub_runner(tmp_path)
    home = tmp_path / "home"
    (home / ".omninode" / "delegation").mkdir(parents=True)
    (home / ".omninode" / "delegation" / "hooks-delegation.json").write_text("{}")
    path = f"{_bin_without_timeout(tmp_path)}:/usr/bin:/bin"
    found = subprocess.run(
        ["/bin/bash", "-c", "command -v timeout || command -v gtimeout"],
        env={"PATH": path},
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode == 0:  # a Linux /usr/bin has timeout: nothing to prove
        pytest.skip(f"timeout is on the system path here: {found.stdout.strip()}")
    env = {
        "HOME": str(home),
        "PATH": path,
        "CLAUDE_PLUGIN_ROOT": str(plugin),
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "ONEX_HOOKS_MASK": "0x7fffffffffffffff",
    }
    result = subprocess.run(
        ["/bin/bash", str(plugin / _HOOK)],
        input=json.dumps(_AGENT_CALL),
        env={**env, "TMPDIR": os.environ.get("TMPDIR", "/tmp")},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    log = tmp_path / "state" / "hooks" / "logs" / "pre-tool-delegation.log"
    logged = log.read_text() if log.exists() else ""
    assert "runner exited 127" not in logged, logged
    assert result.returncode == 2, (result.returncode, result.stderr, logged)
    assert "DELEGATED: stub routed to test-model" in result.stderr
