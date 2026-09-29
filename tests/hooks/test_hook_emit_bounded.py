# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20110 AC3-AC5: a hook emit that misses its budget fails loud and leaks nothing.

Operator ruling, 2026-09-29: a hook may not fail silently; an emit that
cannot complete stops the work and raises an alarm, with no alternate path.
These tests hold the emit path's lock, then assert the bounded runner exits
2 inside its budget with the cause named, that nothing in the emitter's
process group survives, and that the operator alarm fires once per episode.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_HOOKS = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks"
_LIB = _HOOKS / "lib"
_SCRIPTS = _HOOKS / "scripts"
_RUNNER = _LIB / "hook_emit_bounded.py"
_APPEND = _LIB / "hook_emit_append.py"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    alarm_log = tmp_path / "alarms.log"
    alarm = tmp_path / "alarm.sh"
    alarm.write_text(f'#!/bin/bash\nprintf "%s|%s\\n" "$1" "$2" >> "{alarm_log}"\n')
    alarm.chmod(0o755)
    e = dict(os.environ)
    e.update(
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_EMIT_ALARM_CMD=str(alarm),
        ONEX_EMIT_EPISODE_MARKER=str(tmp_path / "episode"),
    )
    e.pop("ONEX_HOOK_EMIT_BUDGET_S", None)
    return e


def _alarms(env: dict[str, str]) -> list[str]:
    path = Path(env["ONEX_EMIT_ALARM_CMD"]).with_name("alarms.log")
    return path.read_text().splitlines() if path.exists() else []


def _run(
    env: dict[str, str], *args: str, budget: float = 5.0
) -> subprocess.CompletedProcess[str]:
    log = Path(env["ONEX_STATE_DIR"]) / "hook.log"
    return subprocess.run(
        [
            sys.executable,
            str(_RUNNER),
            "--label",
            "test.emit",
            "--log",
            str(log),
            "--budget",
            str(budget),
            "--",
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _group_alive(pgid: int) -> bool:
    out = subprocess.run(
        ["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True, check=True
    )
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == str(pgid) and not parts[1].startswith("Z"):
            return True
    return False


@pytest.fixture
def held_turn_lock(tmp_path: Path) -> Iterator[Path]:
    """Hold the per-session turn counter lock, the lock a prompt emit takes."""
    turn = tmp_path / "state" / "hook_turns"
    turn.mkdir(parents=True)
    path = turn / "sess-lock.turn"
    fh = path.open("a+")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        yield path
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def _append_cmd(tmp_path: Path) -> list[str]:
    return [
        sys.executable,
        str(_APPEND),
        "--event-type",
        "prompt.submitted",
        "--session-id",
        "sess-lock",
        "--journal-dir",
        str(tmp_path / "state" / "hook_emit_journal"),
    ]


def test_lock_held_misses_budget_exits_2_and_kills_group(
    env: dict[str, str], tmp_path: Path, held_turn_lock: Path
) -> None:
    env["ONEX_HOOK_LOCK_WAIT_S"] = "60"  # the outer budget must be what fires
    t0 = time.monotonic()
    proc = _run(env, *_append_cmd(tmp_path), budget=1.0)
    elapsed = time.monotonic() - t0
    assert proc.returncode == 2, proc.stderr
    assert elapsed < 4.0, f"runner took {elapsed:.1f}s against a 1s budget"
    assert (
        "BLOCKED: hook emit 'test.emit' did not complete within its 1s budget"
        in proc.stderr
    )
    m = re.search(r"process group (\d+) was killed", proc.stderr)
    assert m, proc.stderr
    time.sleep(0.3)
    assert not _group_alive(int(m.group(1))), (
        "a process of the emitter's group survived"
    )
    assert len(_alarms(env)) == 1


def test_lock_held_names_the_lock_as_the_cause(
    env: dict[str, str], tmp_path: Path, held_turn_lock: Path
) -> None:
    env["ONEX_HOOK_LOCK_WAIT_S"] = "0.3"
    proc = _run(env, *_append_cmd(tmp_path), budget=5.0)
    assert proc.returncode == 2, proc.stderr
    assert "exited 1" in proc.stderr
    assert "turn counter lock" in proc.stderr and "busy" in proc.stderr, proc.stderr
    assert "NOT journalled" in proc.stderr


def test_grandchild_is_killed_with_the_group(
    env: dict[str, str], tmp_path: Path
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    proc = _run(
        env, "/bin/bash", "-c", f"sleep 60 & echo $! > {pidfile}; wait", budget=0.5
    )
    assert proc.returncode == 2
    grandchild = int(pidfile.read_text())
    time.sleep(0.3)
    state = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(grandchild)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert state.stdout.strip() in ("", "Z"), (
        f"grandchild {grandchild} survived: {state.stdout!r}"
    )


def test_success_exits_0_and_journals(env: dict[str, str], tmp_path: Path) -> None:
    proc = _run(env, *_append_cmd(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "" and proc.stderr == ""
    assert list((tmp_path / "state" / "hook_emit_journal").glob("*.json"))
    assert _alarms(env) == []


def test_alarm_once_per_episode(env: dict[str, str]) -> None:
    for _ in range(3):
        assert _run(env, "/usr/bin/false").returncode == 2
    assert len(_alarms(env)) == 1, "one alarm per failure episode, not per call"
    assert Path(env["ONEX_EMIT_EPISODE_MARKER"]).exists()

    assert _run(env, "/usr/bin/true").returncode == 0
    assert not Path(env["ONEX_EMIT_EPISODE_MARKER"]).exists(), (
        "success closes the episode"
    )

    assert _run(env, "/usr/bin/false").returncode == 2
    alarms = _alarms(env)
    assert len(alarms) == 2, "a new episode alarms again"
    assert alarms[0].startswith("hook_emit_failed|") and "test.emit" in alarms[0]


def test_concurrent_failures_alarm_once(env: dict[str, str]) -> None:
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                str(_RUNNER),
                "--label",
                "x",
                "--budget",
                "5",
                "--",
                "/usr/bin/false",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        for _ in range(8)
    ]
    assert all(p.wait(timeout=60) == 2 for p in procs)
    assert len(_alarms(env)) == 1


def test_fail_exit_blocks_except_on_a_stop_rerun() -> None:
    lib = _LIB / "emit_bounded.sh"
    for payload, expected in (
        ('{"hook_event_name":"PreToolUse"}', 2),
        ('{"hook_event_name":"Stop","stop_hook_active": true}', 1),
    ):
        rc = subprocess.run(
            [
                "/bin/bash",
                "-c",
                f'source "{lib}"; onex_emit_fail_exit "$1"',
                "x",
                payload,
            ],
            check=False,
        ).returncode
        assert rc == expected, payload


_EMIT_CALL = re.compile(
    r'"\$PYTHON_CMD" "\$(_EMIT_DISPATCH_PY|_HOOK_CAPTURE_PY|_CONTENT_CAPTURE_PY|append_py)"'
)
_EMITTING_SCRIPTS = (
    "common.sh",
    "claude_hook_capture.sh",
    "post_tool_use_bus_mirror.sh",
    "user_prompt_submit_bus_mirror.sh",
    "stop_content_capture.sh",
    "session_start_bus_mirror.sh",
    "session_end_bus_mirror.sh",
)


@pytest.mark.parametrize("name", _EMITTING_SCRIPTS)
def test_no_disowned_emit(name: str) -> None:
    """Every emit runs through onex_emit_bounded; none is a bare background job."""
    lines = (_SCRIPTS / name).read_text().splitlines()
    calls = [i for i, line in enumerate(lines) if _EMIT_CALL.search(line)]
    assert calls, f"{name}: no emit call found; the scan is stale"
    for i in calls:
        window = "\n".join(lines[max(i - 1, 0) : i + 1])
        assert "onex_emit_bounded" in window, (
            f"{name}:{i + 1} emits outside the bounded runner"
        )


def test_runner_has_no_spool_fail_open_or_kill_switch() -> None:
    src = _RUNNER.read_text().lower()
    for word in ("spool_dir", "fail_open", "hooks_disable", "kill_switch"):
        assert word not in src, word
