# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the SessionStart bus-mirror hook (OMN-16162).

Proves:
  * AC1 -- the hook direct-dispatches ``node_event_emit_effect_dispatch.py``
    with ``event_type=onex.evt.omniclaude.session-started.v1`` and a
    payload built from stdin.
  * The dispatch is backgrounded / non-blocking: the hook process returns
    long before a deliberately slow stand-in dispatcher would finish.
  * AC3 -- malformed stdin and a missing Python interpreter never raise or
    block the session; the hook always exits 0.

A stand-in ``PLUGIN_PYTHON_BIN`` (a plain bash script, not a real Python
interpreter -- ``find_python()``'s escape hatch only requires an executable
file) replaces the real dispatch call so these tests never touch Kafka or
require omnimarket to be importable.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "session_start_bus_mirror.sh"
)

_STDIN_PAYLOAD = json.dumps(
    {
        "session_id": "test-session-16162",
        "cwd": str(_REPO_ROOT),
        "hook_event_name": "SessionStart",
    }
)

_SLOW_STUB = """#!/bin/bash
# Test stand-in for the Python interpreter: records its own argv immediately,
# then sleeps to prove the caller does not wait for it (non-blocking).
printf '%s\\n' "$@" > "{marker}"
sleep {sleep_seconds}
exit 0
"""

_FAST_STUB = """#!/bin/bash
printf '%s\\n' "$@" > "{marker}"
exit 0
"""


def _write_stub(path: Path, marker: Path, *, sleep_seconds: float = 0) -> None:
    template = _SLOW_STUB if sleep_seconds else _FAST_STUB
    path.write_text(template.format(marker=marker, sleep_seconds=sleep_seconds))
    path.chmod(0o755)


def _base_env(tmp_path: Path, *, plugin_python_bin: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(_REPO_ROOT)
    env["ONEX_STATE_DIR"] = str(tmp_path / "onex_state")
    if plugin_python_bin is not None:
        env["PLUGIN_PYTHON_BIN"] = plugin_python_bin
    else:
        env.pop("PLUGIN_PYTHON_BIN", None)
    return env


@pytest.mark.unit
def test_session_start_bus_mirror_backgrounds_the_dispatch_call(tmp_path: Path) -> None:
    """The hook must return well before a slow dispatch call finishes (non-blocking)."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    marker = tmp_path / "invocation-argv.txt"
    stub = tmp_path / "fake_python.sh"
    _write_stub(stub, marker, sleep_seconds=6)

    env = _base_env(tmp_path, plugin_python_bin=str(stub))

    start = time.monotonic()
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input=_STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=15,
        env=env,
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, (
        f"Hook must exit 0 (exit {result.returncode}).\nstderr: {result.stderr}"
    )
    assert elapsed < 3.0, (
        f"Hook took {elapsed:.2f}s to return but the stand-in dispatcher sleeps "
        "6s -- the hook is blocking on the emit dispatch instead of "
        "backgrounding it (violates the non-blocking requirement)."
    )


@pytest.mark.unit
def test_session_start_bus_mirror_invokes_direct_dispatch_with_correct_args(
    tmp_path: Path,
) -> None:
    """AC1: the hook invokes node_event_emit_effect_dispatch.py with the
    session-started event type and a payload carrying the session_id.
    """
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    marker = tmp_path / "invocation-argv.txt"
    stub = tmp_path / "fake_python.sh"
    _write_stub(stub, marker, sleep_seconds=0)

    env = _base_env(tmp_path, plugin_python_bin=str(stub))

    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input=_STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=15,
        env=env,
    )
    assert result.returncode == 0, f"Non-zero exit: {result.stderr}"

    # Poll briefly: the invocation is backgrounded, so the marker may land a
    # moment after the hook process itself has already exited.
    deadline = time.monotonic() + 3.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert marker.exists(), (
        "node_event_emit_effect_dispatch.py was never invoked -- expected "
        f"argv marker at {marker}.\nstderr: {result.stderr}"
    )
    argv_lines = marker.read_text().splitlines()
    assert any(
        line.endswith("node_event_emit_effect_dispatch.py") for line in argv_lines
    ), f"Expected the dispatch script path in argv, got: {argv_lines}"
    assert "--event-type" in argv_lines
    event_type_idx = argv_lines.index("--event-type") + 1
    assert argv_lines[event_type_idx] == "onex.evt.omniclaude.session-started.v1"

    assert "--payload" in argv_lines
    payload_idx = argv_lines.index("--payload") + 1
    payload = json.loads(argv_lines[payload_idx])
    assert payload["session_id"] == "test-session-16162"


@pytest.mark.unit
def test_session_start_bus_mirror_exits_zero_on_malformed_stdin(tmp_path: Path) -> None:
    """AC3: malformed JSON on stdin must never block or crash the session."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    stub = tmp_path / "fake_python.sh"
    _write_stub(stub, tmp_path / "unused-marker.txt", sleep_seconds=0)
    env = _base_env(tmp_path, plugin_python_bin=str(stub))

    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input="{not valid json at all",
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, (
        f"Hook must exit 0 on malformed stdin (exit {result.returncode}).\n"
        f"stderr: {result.stderr}"
    )


@pytest.mark.unit
def test_session_start_bus_mirror_exits_zero_on_empty_stdin(tmp_path: Path) -> None:
    """AC3: empty stdin must never block or crash the session."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    stub = tmp_path / "fake_python.sh"
    _write_stub(stub, tmp_path / "unused-marker.txt", sleep_seconds=0)
    env = _base_env(tmp_path, plugin_python_bin=str(stub))

    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input="",
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=10,
        env=env,
    )
    assert result.returncode == 0, f"Non-zero exit on empty stdin: {result.stderr}"


@pytest.mark.unit
def test_session_start_bus_mirror_exits_zero_when_python_missing(
    tmp_path: Path,
) -> None:
    """AC3: a missing Python interpreter (advisory criticality) never hard-fails.

    Points PLUGIN_PYTHON_BIN at a nonexistent path AND strips every other
    find_python() resolution path from the environment, forcing the
    "no valid Python found" branch in common.sh. The OMN-16162 advisory
    carve-out in common.sh must degrade this to exit 0.
    """
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    env = _base_env(tmp_path, plugin_python_bin=str(tmp_path / "does-not-exist"))
    env.pop("CLAUDE_PLUGIN_DATA", None)
    env.pop("ONEX_REGISTRY_ROOT", None)
    env.pop("OMNICLAUDE_PROJECT_ROOT", None)
    # Force the mode-resolution path away from "lite" (which would short-circuit
    # before find_python() ever runs) without relying on a real mode.sh state.
    env["OMNICLAUDE_MODE"] = "full"
    # Strip PATH's python3 resolution to exercise the true hard-failure branch
    # is not reachable here since find_python() falls back to system python3
    # in lite mode only; in full mode with no venv it returns empty, which is
    # exactly the branch under test.

    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input=_STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=15,
        env=env,
    )
    assert result.returncode == 0, (
        "Hook must exit 0 (advisory) when no Python interpreter resolves, not "
        f"hard-fail (exit {result.returncode}).\nstderr: {result.stderr}"
    )
