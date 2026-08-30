# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the PostToolUse bus-mirror hook (OMN-16162 S1).

Proves:
  * AC1 -- the hook direct-dispatches ``node_event_emit_effect_dispatch.py``
    with ``event_type=onex.evt.omniclaude.tool-executed.v1`` and a payload
    carrying the tool name/timing/interrupted-flag ONLY -- never
    tool_input/tool_response content (onex.evt.* preview-safe invariant).
  * The dispatch is backgrounded / non-blocking.
  * The hook emits NOTHING on stdout (silence-on-pass discipline shared with
    post_tool_use_secret_redact_guard.sh -- plain PostToolUse stdout is
    debug-log-only, and this hook never rewrites tool output).
  * AC3 -- malformed stdin and a missing Python interpreter never raise or
    block the session; the hook always exits 0.

Mirrors tests/unit/hooks/test_session_start_bus_mirror.py's structure.
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
    / "post_tool_use_bus_mirror.sh"
)

_STDIN_PAYLOAD = json.dumps(
    {
        "session_id": "test-session-16162-s1",
        "cwd": str(_REPO_ROOT),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "tool_response": {
            "stdout": "on branch dev\n",
            "stderr": "",
            "interrupted": False,
        },
        "duration_ms": 42,
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
def test_post_tool_use_bus_mirror_backgrounds_the_dispatch_call(tmp_path: Path) -> None:
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
    assert result.stdout == "", (
        "PostToolUse bus-mirror hook must emit nothing on stdout (silence-on-"
        f"pass discipline). Got: {result.stdout!r}"
    )


@pytest.mark.unit
def test_post_tool_use_bus_mirror_invokes_direct_dispatch_with_correct_args(
    tmp_path: Path,
) -> None:
    """AC1: the hook invokes node_event_emit_effect_dispatch.py with the
    tool-executed event type and a metadata-only payload -- never
    tool_input/tool_response content.
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
    assert argv_lines[event_type_idx] == "onex.evt.omniclaude.tool-executed.v1"

    assert "--payload" in argv_lines
    payload_idx = argv_lines.index("--payload") + 1
    payload = json.loads(argv_lines[payload_idx])
    assert payload["session_id"] == "test-session-16162-s1"
    assert payload["working_directory"] == _REPO_ROOT.name
    assert payload["tool_name"] == "Bash"
    assert payload["duration_ms"] == 42
    assert payload["interrupted"] is False
    # The critical privacy assertion: no tool_input/tool_response content leaks.
    assert "tool_input" not in payload
    assert "tool_response" not in payload
    assert "command" not in payload
    for value in payload.values():
        assert value != "git status"


@pytest.mark.unit
def test_post_tool_use_bus_mirror_exits_zero_on_malformed_stdin(tmp_path: Path) -> None:
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
def test_post_tool_use_bus_mirror_exits_zero_on_empty_stdin(tmp_path: Path) -> None:
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
def test_post_tool_use_bus_mirror_exits_zero_when_python_missing(
    tmp_path: Path,
) -> None:
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
