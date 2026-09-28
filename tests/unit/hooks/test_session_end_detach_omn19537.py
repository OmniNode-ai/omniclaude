# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-19537: SessionEnd hooks return before their preamble runs.

A headless Claude Code session (2.1.283) gives its SessionEnd hooks about
1.5 s, then cancels a hook that is still running and kills its process group,
while a disowned child of a hook that has already returned survives. The
scheduled ticks' run logs kept showing session_end_bus_mirror.sh cancelled:
its preamble (repo guard, .env and common.sh sourcing, the lane gate) ran in
the foreground, and on a loaded host it outlasted the window before the
backgrounded append was ever reached.

These tests slow the preamble down on purpose, in a copy of the hook tree,
and assert that the hook still returns at once and that the detached copy
still reaches the appender.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_PLUGIN = _REPO_ROOT / "plugins" / "onex"

# The preamble in the copy sleeps this long: well past the harness's ~1.5 s
# SessionEnd budget, so a hook that runs its preamble in the foreground fails.
_SLOW_PREAMBLE_SECONDS = 4


def _slow_plugin_copy(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    shutil.copytree(
        _PLUGIN / "hooks",
        root / "hooks",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copytree(_PLUGIN / "lib", root / "lib")
    common = root / "hooks" / "scripts" / "common.sh"
    common.write_text(
        f"sleep {_SLOW_PREAMBLE_SECONDS}\n" + common.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def _run(
    tmp_path: Path, script: str, payload: dict[str, str]
) -> tuple[float, Path, subprocess.CompletedProcess[str]]:
    root = _slow_plugin_copy(tmp_path)
    marker = tmp_path / "argv.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > "{marker}"\ncat >/dev/null\n')
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_PLUGIN_ROOT": str(root),
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "OMNICLAUDE_MODE": "full",
            "ONEX_STATE_DIR": str(tmp_path / "onex_state"),
            "PLUGIN_PYTHON_BIN": str(stub),
        }
    )
    started = time.monotonic()
    result = subprocess.run(
        ["bash", str(root / "hooks" / "scripts" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=30,
        env=env,
    )
    return time.monotonic() - started, marker, result


def _wait_for(marker: Path) -> bool:
    deadline = time.monotonic() + _SLOW_PREAMBLE_SECONDS + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    return marker.exists()


_SESSION_END = {
    "hook_event_name": "SessionEnd",
    "session_id": "omn19537-detach",
    "reason": "other",
}


@pytest.mark.parametrize(
    ("script", "entrypoint"),
    [
        ("session_end_bus_mirror.sh", "hook_emit_append.py"),
        ("claude_hook_capture.sh", "hook_claude_capture.py"),
    ],
)
def test_a_session_end_hook_returns_before_a_slow_preamble(
    tmp_path: Path, script: str, entrypoint: str
) -> None:
    elapsed, marker, result = _run(tmp_path, script, _SESSION_END)
    assert result.returncode == 0
    assert result.stdout == ""
    assert elapsed < 1.5, (
        f"{script} took {elapsed:.2f}s to return with a {_SLOW_PREAMBLE_SECONDS}s "
        "preamble: it ran the preamble in the foreground, where a headless "
        "session's SessionEnd cancellation would kill it"
    )
    assert _wait_for(marker), (
        f"the detached copy of {script} never reached the appender"
    )
    assert marker.read_text().splitlines()[0].endswith(entrypoint)


def test_other_hooks_keep_the_preamble_in_the_foreground(tmp_path: Path) -> None:
    # Only SessionEnd detaches early: an in-turn hook must read the turn that
    # is current when it fires, so its gates still run before it returns.
    elapsed, marker, result = _run(
        tmp_path,
        "claude_hook_capture.sh",
        {"hook_event_name": "PreToolUse", "session_id": "omn19537-foreground"},
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert elapsed >= _SLOW_PREAMBLE_SECONDS
    assert _wait_for(marker)
    assert marker.read_text().splitlines()[0].endswith("hook_claude_capture.py")
