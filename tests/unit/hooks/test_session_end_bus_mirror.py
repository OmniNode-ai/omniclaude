# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the SessionEnd bus-mirror hook (OMN-16162).

Mirrors ``test_session_start_bus_mirror.py`` for the SessionEnd side. Proves:
  * AC2 -- the hook direct-dispatches ``node_event_emit_effect_dispatch.py``
    with ``event_type=onex.evt.omniclaude.session-ended.v1`` and a payload
    built from stdin.
  * The dispatch is backgrounded / non-blocking.
  * AC3 -- malformed stdin and a missing Python interpreter never raise or
    block the session; the hook always exits 0.
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
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "session_end_bus_mirror.sh"
)

_STDIN_PAYLOAD = json.dumps(
    {
        "session_id": "test-session-end-16162",
        "reason": "clear",
        "hook_event_name": "SessionEnd",
    }
)

_SLOW_STUB = """#!/bin/bash
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
    env["OMNICLAUDE_MODE"] = "full"
    env["ONEX_STATE_DIR"] = str(tmp_path / "onex_state")
    if plugin_python_bin is not None:
        env["PLUGIN_PYTHON_BIN"] = plugin_python_bin
    else:
        env.pop("PLUGIN_PYTHON_BIN", None)
    return env


@pytest.mark.unit
def test_session_end_bus_mirror_backgrounds_the_dispatch_call(tmp_path: Path) -> None:
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
def test_session_end_bus_mirror_invokes_direct_dispatch_with_correct_args(
    tmp_path: Path,
) -> None:
    """AC2: the hook invokes node_event_emit_effect_dispatch.py with the
    session-ended event type and a payload carrying session_id/reason.
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

    deadline = time.monotonic() + 3.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert marker.exists(), (
        "hook_emit_append.py was never invoked -- expected "
        f"argv marker at {marker}.\nstderr: {result.stderr}"
    )
    argv_lines = marker.read_text().splitlines()
    # OMN-17224: the hook now invokes the stdlib-only fast-path appender,
    # not the old inline publisher. The publish moved to the singleton
    # drainer; the hook's argv contract is otherwise unchanged.
    assert any(line.endswith("hook_emit_append.py") for line in argv_lines), (
        f"Expected the fast-path append script in argv, got: {argv_lines}"
    )
    assert not any(
        line.endswith("node_event_emit_effect_dispatch.py") for line in argv_lines
    ), (
        "hook must not invoke the inline publisher -- that is the "
        "OMN-17224 per-tool-call ~30s import regression"
    )
    assert "--event-type" in argv_lines
    event_type_idx = argv_lines.index("--event-type") + 1
    assert argv_lines[event_type_idx] == "onex.evt.omniclaude.session-ended.v1"

    assert "--payload" in argv_lines
    payload_idx = argv_lines.index("--payload") + 1
    payload = json.loads(argv_lines[payload_idx])
    assert payload["session_id"] == "test-session-end-16162"
    assert payload["reason"] == "clear"


@pytest.mark.unit
def test_session_end_bus_mirror_exits_zero_on_malformed_stdin(tmp_path: Path) -> None:
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
def test_session_end_bus_mirror_exits_zero_on_empty_stdin(tmp_path: Path) -> None:
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
def test_session_end_bus_mirror_normalizes_unknown_reason(tmp_path: Path) -> None:
    """An unrecognized 'reason' value must be normalized to 'other', not passed
    through raw -- matching session-end.sh's existing validation convention.
    """
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    marker = tmp_path / "invocation-argv.txt"
    stub = tmp_path / "fake_python.sh"
    _write_stub(stub, marker, sleep_seconds=0)
    env = _base_env(tmp_path, plugin_python_bin=str(stub))

    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        input=json.dumps({"session_id": "test-bad-reason", "reason": "totally-bogus"}),
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
        timeout=15,
        env=env,
    )
    assert result.returncode == 0, f"Non-zero exit: {result.stderr}"

    deadline = time.monotonic() + 3.0
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), f"Dispatch never invoked.\nstderr: {result.stderr}"

    argv_lines = marker.read_text().splitlines()
    payload_idx = argv_lines.index("--payload") + 1
    payload = json.loads(argv_lines[payload_idx])
    assert payload["reason"] == "other"


@pytest.mark.unit
def test_session_end_bus_mirror_exits_zero_when_python_missing(tmp_path: Path) -> None:
    """AC3: a missing Python interpreter (advisory criticality) never hard-fails."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"

    env = _base_env(tmp_path, plugin_python_bin=str(tmp_path / "does-not-exist"))
    env.pop("CLAUDE_PLUGIN_DATA", None)
    env.pop("ONEX_REGISTRY_ROOT", None)
    env.pop("OMNICLAUDE_PROJECT_ROOT", None)
    env["OMNICLAUDE_MODE"] = "full"

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
