# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for post-tool-delegation-counter.sh read-only Bash classification (OMN-4620).

Verifies:
- Known read-only Bash commands do NOT increment the write counter
- Mutating Bash commands still increment the write counter
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

# Repo root: tests/unit/hooks/scripts/ → 4 levels up
_REPO_ROOT = Path(__file__).parents[4]


def run_hook(
    tool_name: str, cmd: str = "", session_id: str = "test-sess"
) -> tuple[int, str]:
    payload = json.dumps(
        {
            "tool_name": tool_name,
            "session_id": session_id,
            "tool_input": {"command": cmd},
        }
    )
    env = {
        **os.environ,
        "OMNICLAUDE_MODE": "full",
        # Bypass the hook runtime daemon so the shell-based counter logic
        # (counter files in /tmp) is exercised instead of the daemon path.
        "HOOK_RUNTIME_SOCKET": "/tmp/nonexistent-test-socket",
    }
    proc = subprocess.run(
        ["bash", "plugins/onex/hooks/scripts/post-tool-delegation-counter.sh"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout


@pytest.mark.unit
def test_readonly_bash_does_not_increment_write_counter(tmp_path: object) -> None:
    """Known read-only Bash commands should NOT count toward write threshold."""
    import hashlib

    sid = f"test-ro-{hashlib.md5(str(tmp_path).encode()).hexdigest()[:8]}"  # noqa: S324
    read_only_cmds = [
        "ls -la",
        "grep foo bar.py",
        "git log --oneline",
        "git diff HEAD",
        "git status",
        "gh pr list",
        "docker ps",
        "docker logs foo",
    ]
    for cmd in read_only_cmds:
        rc, _ = run_hook("Bash", cmd, session_id=sid)
        assert rc == 0, f"Read-only Bash '{cmd}' should exit 0, got {rc}"
    counter_file = f"/tmp/omniclaude-write-count-{sid}"
    if os.path.exists(counter_file):
        count = int(open(counter_file).read().strip())  # noqa: SIM115
        assert count == 0, f"Write counter should be 0 for read-only calls, got {count}"


@pytest.mark.unit
def test_mutating_bash_still_increments_write_counter(tmp_path: object) -> None:
    """Mutating Bash commands must still count toward write threshold."""
    import hashlib

    sid = f"test-mut-{hashlib.md5(str(tmp_path).encode()).hexdigest()[:8]}"  # noqa: S324
    mutating_cmds = ["touch /tmp/x", "git checkout -b foo", "docker compose up"]
    for cmd in mutating_cmds:
        run_hook("Bash", cmd, session_id=sid)
    counter_file = f"/tmp/omniclaude-write-count-{sid}"
    assert os.path.exists(counter_file), (
        "Write counter file must exist after mutating Bash calls"
    )
    count = int(open(counter_file).read().strip())  # noqa: SIM115
    assert count >= len(mutating_cmds), (
        f"Expected >={len(mutating_cmds)} writes, got {count}"
    )
