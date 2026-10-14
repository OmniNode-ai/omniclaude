# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18603: a lane with no repository checkout is still a captured lane.

The merge sweep plans its diagnose lane with ``repo: None``: it reads the landing
controller's own files, so the runner gives it a scratch directory and no clone
(Claude Code reports ``isGitRepo: False`` for it). Every hook of that lane ran,
but ``claude_hook_capture.sh`` asks ``is_omninode_repo`` about the session's
directory first, found no OmniNode marker in an empty directory, and exited 0
before it logged a word. On lab host h202, 2026-10-13T10:27Z to 10:35Z, the lane
made 21 tool calls and the capture log held 172 invocations, every one of them a
sibling lane's: the lane's session has no row in ``claude_hook_events`` at all, and
neither has any of the 65 diagnose lanes the ledger counts for the day.

The launcher declares every dispatched lane in ``ONEX_LANE``. That declaration, not
the working directory, decides that the process is this workspace's, so the capture
runs for it whatever its cwd holds. A session with no lane declared and no OmniNode
repository is somebody else's project and is still left alone.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPT = (
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "claude_hook_capture.sh"
)
_PAYLOAD = {"hook_event_name": "PreToolUse", "session_id": "s", "tool_name": "Bash"}


def _run(tmp_path: Path, *, lane: str | None, cwd_has_repo: bool) -> Path:
    """Run the wrapper from a scratch cwd; return the file the stub interpreter wrote."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "argv.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(
        f'#!/bin/bash\ncase "$1" in *hook_emit_bounded.py) exec "{sys.executable}" "$@" ;; esac\n'
        f'printf "%s\\n" "$@" > "{marker}"\ncat >/dev/null\n'
    )
    stub.chmod(0o755)
    cwd = tmp_path / "lane_cwd"
    cwd.mkdir()
    if cwd_has_repo:
        (cwd / ".onex_state").mkdir()
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ONEX_LANE", "CLAUDE_PROJECT_DIR")
    }
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(cwd),
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "onex_state"),
            "PLUGIN_PYTHON_BIN": str(stub),
            "ONEX_HOOK_EMIT_BUDGET_S": "5",
            "ONEX_EMIT_ALARM_CMD": "/usr/bin/true",
            "ONEX_EMIT_EPISODE_MARKER": str(tmp_path / "episode"),
        }
    )
    if lane is not None:
        env["ONEX_LANE"] = lane
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input=json.dumps(_PAYLOAD),
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    return marker


def test_a_dispatched_lane_with_no_repository_checkout_is_captured(
    tmp_path: Path,
) -> None:
    marker = _run(
        tmp_path, lane="sweep-orchestrator-31d9-1023-diagnose-1", cwd_has_repo=False
    )
    assert marker.exists(), (
        "the capture never reached its interpreter for a repo-less lane"
    )
    assert marker.read_text().splitlines()[0].endswith("hook_claude_capture.py")


def test_a_session_with_no_lane_and_no_omninode_repository_is_still_left_alone(
    tmp_path: Path,
) -> None:
    assert not _run(tmp_path, lane=None, cwd_has_repo=False).exists()


def test_positive_control_a_repository_session_is_captured_with_or_without_a_lane(
    tmp_path: Path,
) -> None:
    assert _run(tmp_path / "a", lane=None, cwd_has_repo=True).exists()
    assert _run(tmp_path / "b", lane="some-lane", cwd_has_repo=True).exists()
