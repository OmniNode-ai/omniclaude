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


def test_blocked_text_names_the_elapsed_time(env: dict[str, str]) -> None:
    """Titration needs the time an emit took, not only the budget it missed."""
    proc = _run(env, "/bin/sleep", "5", budget=0.5)
    assert proc.returncode == 2
    assert re.search(r"killed after \d+\.\ds", proc.stderr), proc.stderr
    proc = _run(env, "/usr/bin/false")
    assert re.search(r"exited 1 after \d+\.\ds", proc.stderr), proc.stderr


def test_import_installs_no_signal_handlers() -> None:
    """The drainer imports the runner for its alarm; its handlers must survive."""
    code = (
        "import signal, sys\n"
        f"sys.path.insert(0, {str(_LIB)!r})\n"
        "before = signal.getsignal(signal.SIGHUP)\n"
        "import hook_emit_bounded\n"
        "assert signal.getsignal(signal.SIGHUP) is before\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


def test_drainer_drop_alarms_once_per_episode(
    env: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bound eviction is lost telemetry: it alarms, once per drop episode."""
    for key in ("ONEX_EMIT_ALARM_CMD", "ONEX_EMIT_EPISODE_MARKER"):
        monkeypatch.setenv(key, env[key])
    sys.path.insert(0, str(_LIB))
    import hook_emit_bounded as bounded
    import hook_emit_drainer as drainer

    journal_dir = tmp_path / "state" / "hook_emit_journal"
    marker = tmp_path / "drop-episode"
    for dropped in (3, 5, 0, 2):
        drainer.alarm_on_drop(
            dropped,
            10,
            journal_dir,
            marker,
            bounded.raise_alarm_once,
            bounded.close_episode,
        )
    alarms = _alarms(env)
    assert len(alarms) == 2, alarms
    assert all(a.startswith("hook_emit_journal_dropped|") for a in alarms)
    assert "dropped 3 oldest" in alarms[0] and "dropped 2 oldest" in alarms[1]
    assert marker.exists(), "the second episode is still open"


# ---------------------------------------------------------------------------
# OMN-20118: a writer of the hook lib directory runs in a forked child
# ---------------------------------------------------------------------------


def test_lib_writer_is_forked_not_exec_d(env: dict[str, str], tmp_path: Path) -> None:
    """The interpreter named in the command is never started for a lib writer.

    The command names a wrapper that declares itself this interpreter and does
    not exist, so an exec would fail; the fork runs the writer inside the
    runner's own interpreter and the record lands.
    """
    cmd = _append_cmd(tmp_path)
    cmd[0] = str(tmp_path / "no-such-dir" / "python3")
    proc = _run({**env, "ONEX_HOOK_PYTHON_WRAPPER": cmd[0]}, *cmd)
    assert proc.returncode == 0, proc.stderr
    assert list((tmp_path / "state" / "hook_emit_journal").glob("*.json"))


def test_a_different_program_is_exec_d(env: dict[str, str], tmp_path: Path) -> None:
    """A program that is not this interpreter (a stub, another interpreter) is
    exec'd with the writer's argv, exactly as before OMN-20118."""
    marker = tmp_path / "argv.txt"
    stub = tmp_path / "fake_python.sh"
    stub.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{marker}"\n')
    stub.chmod(0o755)
    cmd = _append_cmd(tmp_path)
    cmd[0] = str(stub)
    proc = _run(env, *cmd)
    assert proc.returncode == 0, proc.stderr
    assert marker.read_text().splitlines()[0] == str(_APPEND)
    assert not list((tmp_path / "state" / "hook_emit_journal").glob("*.json"))


def test_forked_writer_failure_is_loud(env: dict[str, str], tmp_path: Path) -> None:
    """A writer exiting non-zero in the fork fails the emit exactly as before."""
    journal_file = tmp_path / "state" / "hook_emit_journal"
    journal_file.parent.mkdir(parents=True)
    journal_file.write_text("not a directory")
    proc = _run(env, *_append_cmd(tmp_path))
    assert proc.returncode == 2
    assert "exited 1" in proc.stderr and "NOT journalled" in proc.stderr, proc.stderr
    assert len(_alarms(env)) == 1


def test_only_lib_writers_are_forked(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(_LIB)!r})\n"
        "import hook_emit_bounded as b\n"
        f"assert b.in_process_writer([sys.executable, {str(_APPEND)!r}]) is not None\n"
        f"assert b.in_process_writer(['/bin/bash', {str(_APPEND)!r}]) is None\n"
        f"assert b.in_process_writer([sys.executable, {str(tmp_path / 'x.py')!r}]) is None\n"
        f"assert b.in_process_writer([sys.executable, {str(_LIB / 'emit_bounded.sh')!r}]) is None\n"
        f"assert b.in_process_writer([{str(tmp_path / 'fake_python.sh')!r}, {str(_APPEND)!r}]) is None\n"
        "assert b.in_process_writer(['/usr/bin/false']) is None\n"
    )
    (tmp_path / "x.py").write_text("")
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
