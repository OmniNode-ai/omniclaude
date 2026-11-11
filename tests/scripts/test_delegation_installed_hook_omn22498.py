# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The delegation hook runs as a customer installed it (OMN-22498, Amendment 2).

``scripts/install-delegation.sh --apply`` registers the delegation hook in
``~/.claude/settings.json``, pointing at copies under ``~/.omninode/delegation``.
Claude Code runs that command with no ``CLAUDE_PLUGIN_ROOT``, from the
customer's own project. These tests install into a scratch HOME and run the
installed command exactly that way.

Failure modes:
  F1. A helper the hook sources (error-guard.sh and what it loads) is not
      copied, so the hook dies before doing anything (exit 1 under /bin/bash
      3.2) or its gate function is undefined and it passes everything through.
  F2. The routing runner (hooks/lib/delegation_hook_runner.py) or the helpers
      the hook resolves relative to itself (mode.sh, repo_guard.sh) are not
      installed, so the hook never reaches a routing decision.
  F3. The installed copy ignores the switch: with bit 11 off it still routes.
  F4. No Python is found: Claude Code runs a settings.json hook with no
      PLUGIN_PYTHON_BIN, so the command itself must carry the interpreter the
      installer resolved. The test environment sets none.

"Reached the routing runner" is read from the hook's own log: it writes
``PASS tool=...`` or ``BLOCK tool=...`` only after the runner returned, and a
``WARN`` line when it found no Python or no runner.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "scripts" / "install-delegation.sh"

_DEFAULT_MASK = 0xFFFFFFFFFFFFFFF
_BIT_11 = 0x800

_AGENT_CALL = json.dumps(
    {
        "tool_name": "Agent",
        "session_id": "omn22498-installed",
        "tool_input": {"prompt": "write a haiku", "subagent_type": "general-purpose"},
    }
)


def _install(tmp_path: Path) -> Path:
    """Run the real installer into a scratch HOME and return that HOME."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    claude = stub_bin / "claude"
    claude.write_text('#!/usr/bin/env bash\necho "claude 1.0.0-stub"\n')
    claude.chmod(0o755)
    env = {
        "HOME": str(home),
        "PATH": f"{stub_bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "TMPDIR": str(tmp_path),
    }
    proc = subprocess.run(
        ["bash", str(_INSTALLER), "--apply", "--skip-pip", "--python", sys.executable],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return home


def _installed_pre_tool_command(home: Path) -> str:
    settings = json.loads((home / ".claude" / "settings.json").read_text())
    commands = [
        hook["command"]
        for group in settings["hooks"].get("PreToolUse", [])
        for hook in group["hooks"]
        if "pre_tool_use_delegation.sh" in hook["command"]
    ]
    assert len(commands) == 1, commands
    return commands[0]


def _run_installed(
    tmp_path: Path, home: Path, mask: int
) -> tuple[subprocess.CompletedProcess[str], Path]:
    project = tmp_path / "customer-project"
    project.mkdir(exist_ok=True)
    (project / "README.md").write_text("a customer's own project\n")
    state = tmp_path / "state"
    env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(tmp_path),
        "ONEX_STATE_DIR": str(state),
        "ONEX_HOOKS_MASK": hex(mask),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    command = _installed_pre_tool_command(home)
    proc = subprocess.run(
        ["/bin/bash", "-c", command],
        input=_AGENT_CALL + "\n",
        capture_output=True,
        text=True,
        cwd=str(project),
        env=env,
        check=False,
        timeout=60,
    )
    return proc, state / "hooks" / "logs" / "pre-tool-delegation.log"


def _log_text(log: Path) -> str:
    return log.read_text() if log.exists() else ""


@pytest.mark.unit
def test_delegation_not_lite_installed_hook_reaches_the_routing_runner(
    tmp_path: Path,
) -> None:
    """F1, F2, F4: the installed copy, run as Claude Code runs it, routes the call."""
    home = _install(tmp_path)
    proc, log = _run_installed(tmp_path, home, _DEFAULT_MASK)
    text = _log_text(log)
    assert proc.returncode in (0, 2), proc.stderr
    assert "PASS tool=Agent" in text or "BLOCK tool=Agent" in text, (
        f"no routing decision; log={text!r} stderr={proc.stderr!r}"
    )
    assert "WARN" not in text, text


@pytest.mark.unit
def test_delegation_not_lite_installed_hook_bit_off_passes_through(
    tmp_path: Path,
) -> None:
    """F3: the switch holds on the installed copy."""
    home = _install(tmp_path)
    proc, log = _run_installed(tmp_path, home, _DEFAULT_MASK & ~_BIT_11)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _AGENT_CALL
    text = _log_text(log)
    assert "PASS tool=" not in text and "BLOCK tool=" not in text, text
