# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The auto-checkpoint hook reads no GitHub through gh [OMN-19998].

``post_tool_use_auto_checkpoint.sh`` is registered on PostToolUse (Bash) and
fires after every ``git commit``. It used to run ``gh pr view`` for the
checkpoint's "PR status" line. The gh shim counts every call from under a
Claude or Codex process as a lane read (OMN-20911), so each lane commit spent
the host's read budget and, once it was spent or the verb was strict, wrote a
``gh_shim_lane_read_guard`` refusal row. The hook now points at the local
reader instead of calling gh.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_HOOK = (
    Path(__file__).parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "post_tool_use_auto_checkpoint.sh"
)


def _run_hook(
    tmp_path: Path, command: str
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh_log = tmp_path / "gh-calls.log"
    fake_gh = bindir / "gh"
    fake_gh.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{gh_log}"\n'
        'echo \'{"number":1,"url":"u","state":"OPEN"}\'\n'
    )
    fake_gh.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"OMNICLAUDE_HOOKS_DISABLED", "ONEX_HOOKS_MASK"}
    }
    env.update(
        HOME=str(home),
        PATH=f"{bindir}{os.pathsep}{env.get('PATH', '')}",
        ONEX_LANE="test-lane",
    )
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    done = subprocess.run(
        ["bash", str(_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=60,
        check=False,
    )
    return done, gh_log, home / ".claude" / "handoffs"


def test_commit_checkpoint_makes_no_gh_call(tmp_path: Path) -> None:
    done, gh_log, handoffs = _run_hook(tmp_path, "git commit -m 'x'")
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    # Positive control: the hook did run its commit path and wrote a checkpoint.
    checkpoints = list(handoffs.glob("checkpoint-*.md"))
    assert len(checkpoints) == 1
    assert not gh_log.exists(), f"gh was called: {gh_log.read_text()}"
    assert "pr_state_local.py" in checkpoints[0].read_text()


def test_non_commit_command_writes_nothing(tmp_path: Path) -> None:
    done, gh_log, handoffs = _run_hook(tmp_path, "ls")
    assert done.returncode == 0, done.stderr
    assert not list(handoffs.glob("checkpoint-*.md"))
    assert not gh_log.exists()
