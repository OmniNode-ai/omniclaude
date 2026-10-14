# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18609: a dispatched lane with no repository checkout keeps its mirrored hook events.

The merge sweep plans its diagnose lane with no repository, so the lane runs in a
scratch directory with no OmniNode marker. ``claude_hook_capture.sh`` already lets a
lane the launcher declared in ``ONEX_LANE`` through its repo guard, but the bus-mirror
hooks kept the bare ``is_omninode_repo`` guard and exited before they journalled
anything. Measured on the dev lane's ``claude_hook_events`` on 2026-10-14: the four
diagnose lanes of orchestrator-31d9's sweeps since 08:45Z each hold SessionStart,
PreToolUse, PostToolUse, Stop and SessionEnd rows and **no** UserPromptSubmit row,
while every fix, close and escalation lane of the same sweeps holds one. That row is
journalled by ``user_prompt_submit_bus_mirror.sh``, never by the capture hook. The
same guard dropped the lane's session-started, prompt-submitted, tool-executed,
session-ended and stop-content records.

The launcher's declaration, not the working directory, decides that the process is
this workspace's. A session with no lane declared and no OmniNode repository is
somebody else's project and is still left alone.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPTS = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"

# hook script -> (hook event, the module the stub interpreter must be handed)
_CASES = {
    "user_prompt_submit_bus_mirror.sh": ("UserPromptSubmit", "hook_claude_capture.py"),
    "session_start_bus_mirror.sh": ("SessionStart", "hook_emit_append.py"),
    "post_tool_use_bus_mirror.sh": ("PostToolUse", "hook_emit_append.py"),
    "session_end_bus_mirror.sh": ("SessionEnd", "hook_emit_append.py"),
    "stop_content_capture.sh": ("Stop", "hook_content_capture.py"),
}


def _run(
    tmp_path: Path, script: str, *, lane: str | None, cwd_has_repo: bool
) -> list[str]:
    """Run one hook from a scratch cwd; return the modules the stub interpreter was handed."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(
        f'#!/bin/bash\ncase "$1" in *hook_emit_bounded.py) exec "{sys.executable}" "$@" ;; esac\n'
        f'printf "%s\\n" "${{1##*/}}" >> "{calls}"\ncat >/dev/null\n'
    )
    stub.chmod(0o755)
    cwd = tmp_path / "lane_cwd"
    cwd.mkdir()
    if cwd_has_repo:
        (cwd / ".onex_state").mkdir()
    hook_event, _ = _CASES[script]
    payload = {
        "hook_event_name": hook_event,
        "session_id": "s",
        "cwd": str(cwd),
        "prompt": "p",
        "tool_name": "Bash",
        "tool_input": {"command": "true"},
        "tool_response": {"stdout": ""},
        "last_assistant_message": "done",
    }
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("ONEX_LANE", "CLAUDE_PROJECT_DIR")
    }
    env.update(
        {
            "CLAUDE_PROJECT_DIR": str(cwd),
            "OMNICLAUDE_MODE": "full",
            "OMNICLAUDE_CONTENT_CAPTURE": "1",
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
        ["bash", str(_SCRIPTS / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
        timeout=60,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    # session_end_bus_mirror.sh detaches its emit (the harness kills a slow SessionEnd hook).
    deadline = time.monotonic() + 15
    while not calls.exists() and time.monotonic() < deadline:
        if script != "session_end_bus_mirror.sh":
            break
        time.sleep(0.2)
    return calls.read_text().splitlines() if calls.exists() else []


@pytest.mark.parametrize("script", sorted(_CASES))
def test_a_dispatched_lane_with_no_repository_checkout_is_mirrored(
    tmp_path: Path, script: str
) -> None:
    calls = _run(
        tmp_path,
        script,
        lane="sweep-orchestrator-31d9-1325-diagnose-1",
        cwd_has_repo=False,
    )
    assert _CASES[script][1] in calls, (
        f"{script} never reached {_CASES[script][1]} for a repo-less lane: {calls}"
    )


@pytest.mark.parametrize("script", sorted(_CASES))
def test_a_session_with_no_lane_and_no_omninode_repository_is_still_left_alone(
    tmp_path: Path, script: str
) -> None:
    assert _run(tmp_path, script, lane=None, cwd_has_repo=False) == []


@pytest.mark.parametrize("script", sorted(_CASES))
def test_positive_control_a_repository_session_is_mirrored_with_or_without_a_lane(
    tmp_path: Path, script: str
) -> None:
    module = _CASES[script][1]
    assert module in _run(tmp_path / "a", script, lane=None, cwd_has_repo=True)
    assert module in _run(tmp_path / "b", script, lane="some-lane", cwd_has_repo=True)
