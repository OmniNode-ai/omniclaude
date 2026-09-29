# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The live hook-process canary (OMN-20109).

The suite in this directory proves the hooks behave in CI. It cannot see a host
that is already on fire: a leak that only shows under a real session's load, a
hook path nobody exercised, the per-user process limit closing in. The canary is
the live half: a resident job that, every 60 s, counts hook processes, hook
processes orphaned to pid 1, and the user's process count against the per-user
limit, and alarms the operator once per episode.

The contract tested here:

* thresholds: orphans above 20, user processes above 60 percent of the limit,
  hook processes above 150 each raise a named alarm; at or under them, none;
* one alarm per episode and kind: a second cycle in the same episode does not
  deliver again, and a new episode after a healthy cycle does;
* an alarm that reached no operator channel is retried on the next cycle, and is
  never marked delivered;
* it never fails silently: a measurement that cannot run (the fork that starts
  ``ps`` fails, the very state the canary exists for), an exception inside the
  canary, and a gap in its own heartbeat are each an alarm of their own kind;
* a delivered alarm is a notification AND a ledger STATUS row with state=ALERT.
"""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.hooks_system._harness import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import hook_process_canary as canary  # noqa: E402

NOW = 1_790_000_000.0


def _row(pid: int, ppid: int, uid: int, command: str) -> canary.ProcRow:
    return canary.ProcRow(pid=pid, ppid=ppid, uid=uid, command=command)


def _hook(pid: int, ppid: int = 500, uid: int = 501) -> canary.ProcRow:
    return _row(
        pid, ppid, uid, "/bin/bash /x/plugins/onex/hooks/scripts/claude_hook_capture.sh"
    )


def _python(pid: int, ppid: int = 500, uid: int = 501) -> canary.ProcRow:
    return _row(
        pid,
        ppid,
        uid,
        "/x/.venv/bin/python /x/hooks/lib/hook_emit_append.py --event-type skill.started",
    )


def _other(pid: int, uid: int = 501) -> canary.ProcRow:
    return _row(pid, 1, uid, "/usr/bin/vim notes.txt")


class Sink:
    """Records what the canary delivered, and can be told to fail."""

    def __init__(self, notify_ok: bool = True, ledger_ok: bool = True) -> None:
        self.notify_ok = notify_ok
        self.ledger_ok = ledger_ok
        self.notifications: list[tuple[str, str]] = []
        self.rows: list[str] = []

    def notify(self, title: str, message: str) -> bool:
        self.notifications.append((title, message))
        return self.notify_ok

    def ledger(self, row: str) -> bool:
        self.rows.append(row)
        return self.ledger_ok


def _canary(tmp_path: Path, sink: Sink, rows_limit, **thresholds) -> canary.Canary:
    def sampler() -> tuple[list[canary.ProcRow], int | None]:
        value = rows_limit() if callable(rows_limit) else rows_limit
        return value

    return canary.Canary(
        state_dir=tmp_path,
        thresholds=canary.Thresholds(**thresholds),
        sampler=sampler,
        notify=sink.notify,
        append_ledger=sink.ledger,
        uid=501,
        host="testhost",
        interval_seconds=60,
    )


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def test_measure_counts_hook_processes_orphans_and_user_processes() -> None:
    rows = [
        _hook(10),
        _hook(11, ppid=1),
        _python(12, ppid=1),
        _python(13),
        _other(14),
        _hook(15, uid=0),  # another user's hook is not this user's process
    ]
    reading = canary.measure(rows, uid=501, limit=1000, self_pid=9999)
    assert reading.hook_processes == 4
    assert reading.hook_pythons == 2
    assert reading.hook_orphans == 2
    assert reading.user_processes == 5
    assert reading.limit == 1000


def test_measure_does_not_count_the_resident_drainer_as_a_leaked_hook() -> None:
    drainer = _row(
        20,
        1,
        501,
        "/x/.venv/bin/python /x/plugins/onex/hooks/lib/hook_emit_drainer.py --log-level INFO",
    )
    reading = canary.measure([drainer, _hook(21)], uid=501, limit=None, self_pid=9999)
    assert reading.hook_processes == 1
    assert reading.hook_orphans == 0
    assert reading.user_processes == 2, "it is still one of the user's processes"


def test_measure_never_counts_the_canary_itself() -> None:
    rows = [
        _row(77, 1, 501, "/usr/bin/python3 hook_process_canary.py --loop"),
        _hook(78),
    ]
    reading = canary.measure(rows, uid=501, limit=None, self_pid=77)
    assert reading.user_processes == 1
    assert reading.hook_processes == 1


def test_parse_ps_output() -> None:
    text = "  1     0     0 /sbin/launchd\n 42     1   501 /bin/bash /x/plugins/onex/hooks/scripts/a.sh --flag\n"
    rows = canary.parse_ps(text)
    assert [(r.pid, r.ppid, r.uid) for r in rows] == [(1, 0, 0), (42, 1, 501)]
    assert rows[1].command.endswith("a.sh --flag")


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------


def _kinds(reading: canary.Reading) -> set[str]:
    return {a.kind for a in canary.evaluate(reading, canary.Thresholds())}


def _reading(**kw: object) -> canary.Reading:
    base = {
        "hook_processes": 0,
        "hook_pythons": 0,
        "hook_orphans": 0,
        "user_processes": 100,
        "limit": 1000,
    }
    base.update(kw)
    return canary.Reading(**base)  # type: ignore[arg-type]


def test_at_the_thresholds_there_is_no_alarm() -> None:
    assert (
        _kinds(_reading(hook_orphans=20, hook_processes=150, user_processes=600))
        == set()
    )


def test_each_threshold_raises_its_own_alarm() -> None:
    assert _kinds(_reading(hook_orphans=21)) == {"hook-orphans"}
    assert _kinds(_reading(hook_processes=151)) == {"hook-process-count"}
    assert _kinds(_reading(user_processes=601)) == {"user-process-limit"}


def test_an_unknown_limit_does_not_raise_the_ratio_alarm() -> None:
    assert _kinds(_reading(user_processes=99999, limit=None)) == set()


# ---------------------------------------------------------------------------
# Episodes and delivery
# ---------------------------------------------------------------------------

_BAD = ([_hook(i, ppid=1) for i in range(30)], 1000)
_GOOD = ([_other(1)], 1000)


def test_a_healthy_cycle_writes_a_heartbeat_and_delivers_nothing(
    tmp_path: Path,
) -> None:
    sink = Sink()
    result = _canary(tmp_path, sink, _GOOD).run_once(NOW)
    assert result.alarms == []
    assert not sink.notifications and not sink.rows
    beat = json.loads((tmp_path / "heartbeat.json").read_text())
    assert beat["at"] == NOW


def test_an_alarm_is_a_notification_and_a_ledger_status_row(tmp_path: Path) -> None:
    sink = Sink()
    result = _canary(tmp_path, sink, _BAD).run_once(NOW)
    assert {a.kind for a in result.alarms} == {"hook-orphans"}
    assert result.delivered
    assert len(sink.notifications) == 1
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert " | STATUS | lane=hook-process-canary | " in row
    assert (
        "state=ALERT" in row and "kinds=hook-orphans" in row and "host=testhost" in row
    )
    assert "orphans=30" in row
    assert all("|" not in field for field in row.split(" | ")), (
        "a pipe inside a field breaks the ledger row"
    )


def test_the_same_episode_is_delivered_once(tmp_path: Path) -> None:
    sink = Sink()
    c = _canary(tmp_path, sink, _BAD)
    c.run_once(NOW)
    c.run_once(NOW + 60)
    c.run_once(NOW + 120)
    assert len(sink.notifications) == 1
    assert len(sink.rows) == 1


def test_a_new_episode_after_a_healthy_cycle_is_delivered_again(tmp_path: Path) -> None:
    sink = Sink()
    state = {"value": _BAD}
    c = _canary(tmp_path, sink, lambda: state["value"])
    c.run_once(NOW)
    state["value"] = _GOOD
    c.run_once(NOW + 60)
    state["value"] = _BAD
    c.run_once(NOW + 120)
    assert len(sink.notifications) == 2
    assert len(sink.rows) == 2


def test_a_new_kind_inside_an_episode_is_delivered_once(tmp_path: Path) -> None:
    sink = Sink()
    orphans_only = ([_hook(i, ppid=1) for i in range(30)], 1000)
    also_limit = (
        [_hook(i, ppid=1) for i in range(30)] + [_other(1000 + i) for i in range(700)],
        1000,
    )
    state = {"value": orphans_only}
    c = _canary(tmp_path, sink, lambda: state["value"])
    c.run_once(NOW)
    state["value"] = also_limit
    c.run_once(NOW + 60)
    c.run_once(NOW + 120)
    assert len(sink.notifications) == 2
    assert "user-process-limit" in sink.rows[1]


def test_an_alarm_no_channel_carried_is_retried_and_not_marked_delivered(
    tmp_path: Path,
) -> None:
    sink = Sink(notify_ok=False, ledger_ok=False)
    c = _canary(tmp_path, sink, _BAD)
    first = c.run_once(NOW)
    assert not first.delivered
    second = c.run_once(NOW + 60)
    assert not second.delivered
    assert len(sink.notifications) == 2, "an undelivered alarm must be attempted again"
    sink.notify_ok = True
    third = c.run_once(NOW + 120)
    assert third.delivered
    c.run_once(NOW + 180)
    assert len(sink.notifications) == 3, "once delivered, the episode stays quiet"


def test_one_working_channel_is_enough_to_count_as_delivered(tmp_path: Path) -> None:
    sink = Sink(notify_ok=False, ledger_ok=True)
    assert _canary(tmp_path, sink, _BAD).run_once(NOW).delivered


def test_the_alert_is_always_written_to_a_local_file(tmp_path: Path) -> None:
    sink = Sink(notify_ok=False, ledger_ok=False)
    _canary(tmp_path, sink, _BAD).run_once(NOW)
    alert = json.loads((tmp_path / "ALERT.json").read_text())
    assert alert["kinds"] == ["hook-orphans"]


# ---------------------------------------------------------------------------
# It never fails silently
# ---------------------------------------------------------------------------


def _fork_fails() -> tuple[list[canary.ProcRow], int | None]:
    raise OSError(errno.EAGAIN, "Resource temporarily unavailable")


def test_a_fork_failure_is_an_alarm_not_a_skipped_cycle(tmp_path: Path) -> None:
    sink = Sink()
    result = _canary(tmp_path, sink, _fork_fails).run_once(NOW)
    assert {a.kind for a in result.alarms} == {"cannot-measure"}
    assert result.delivered
    assert (
        "EAGAIN" in sink.rows[0] or "Resource temporarily unavailable" in sink.rows[0]
    )


def test_an_exception_inside_the_canary_is_an_alarm(tmp_path: Path) -> None:
    def boom() -> tuple[list[canary.ProcRow], int | None]:
        raise RuntimeError("sampler blew up")

    sink = Sink()
    result = _canary(tmp_path, sink, boom).run_once(NOW)
    assert {a.kind for a in result.alarms} == {"canary-error"}
    assert "sampler blew up" in sink.rows[0]


def test_a_gap_in_the_heartbeat_is_an_alarm(tmp_path: Path) -> None:
    sink = Sink()
    c = _canary(tmp_path, sink, _GOOD)
    c.run_once(NOW)
    result = c.run_once(NOW + 60 * 4)  # more than three intervals since the last beat
    assert {a.kind for a in result.alarms} == {"canary-gap"}
    assert "240" in sink.rows[0]


def test_no_gap_alarm_when_the_canary_runs_on_time(tmp_path: Path) -> None:
    sink = Sink()
    c = _canary(tmp_path, sink, _GOOD)
    c.run_once(NOW)
    assert c.run_once(NOW + 65).alarms == []


# ---------------------------------------------------------------------------
# The command line, against the real host
# ---------------------------------------------------------------------------


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _cli(tmp_path: Path, *args: str, env_extra: dict[str, str] | None = None):
    notify_log = tmp_path / "notify.log"
    ledger_log = tmp_path / "ledger.log"
    notify = _script(
        tmp_path / "notify.sh", f'printf "%s|%s\\n" "$1" "$2" >> {notify_log}\n'
    )
    ledger = _script(tmp_path / "ledger.sh", f'printf "%s\\n" "$1" >> {ledger_log}\n')
    env = dict(os.environ)
    env.update(
        {
            "HOOK_CANARY_NOTIFY_CMD": str(notify),
            "HOOK_CANARY_LEDGER_APPEND_CMD": str(ledger),
        }
    )
    env.update(env_extra or {})
    run = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "hook_process_canary.py"),
            "--once",
            "--state-dir",
            str(tmp_path / "state"),
            *args,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    return run, notify_log, ledger_log


def test_cli_healthy_host_exits_zero_and_beats(tmp_path: Path) -> None:
    run, notify_log, _ = _cli(
        tmp_path,
        "--orphans-max",
        "100000",
        "--hook-procs-max",
        "100000",
        "--user-ratio-max",
        "1.0",
    )
    assert run.returncode == 0, run.stderr
    assert not notify_log.exists()
    assert (tmp_path / "state" / "heartbeat.json").is_file()


def test_cli_forced_threshold_proves_the_alarm_end_to_end(tmp_path: Path) -> None:
    """The proof the live install uses: a threshold no host can meet raises the
    alarm through the real command line, the notifier and the ledger command."""
    run, notify_log, ledger_log = _cli(tmp_path, "--hook-procs-max", "-1")
    assert run.returncode == 3, run.stdout + run.stderr
    assert "hook-process-count" in notify_log.read_text()
    row = ledger_log.read_text()
    assert " | STATUS | lane=hook-process-canary | " in row and "state=ALERT" in row


def test_cli_an_undeliverable_alarm_exits_nonzero_and_says_so(tmp_path: Path) -> None:
    run, _notify, _ledger = _cli(
        tmp_path,
        "--hook-procs-max",
        "-1",
        env_extra={
            "HOOK_CANARY_NOTIFY_CMD": "/nonexistent/notify",
            "HOOK_CANARY_LEDGER_APPEND_CMD": "/nonexistent/ledger",
        },
    )
    assert run.returncode == 4, run.stdout + run.stderr
    assert "UNDELIVERED" in run.stderr


def test_cli_an_internal_error_is_an_alarm_and_a_nonzero_exit(tmp_path: Path) -> None:
    run, notify_log, _ = _cli(tmp_path, env_extra={"HOOK_CANARY_FORCE_ERROR": "1"})
    assert run.returncode == 5, run.stdout + run.stderr
    assert "canary-error" in notify_log.read_text()


# ---------------------------------------------------------------------------
# The installer
# ---------------------------------------------------------------------------

_INSTALLER = REPO_ROOT / "scripts" / "install-hook-process-canary.sh"


def test_installer_refuses_without_a_state_dir(tmp_path: Path) -> None:
    run = subprocess.run(
        ["bash", str(_INSTALLER), "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 2
    assert "--state-dir is required" in run.stderr


@pytest.mark.skipif(
    sys.platform != "darwin", reason="renders the launchd plist on macOS"
)
def test_installer_renders_a_complete_plist(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.md"
    run = subprocess.run(
        [
            "bash",
            str(_INSTALLER),
            "--dry-run",
            "--state-dir",
            str(tmp_path / "state"),
            "--ledger",
            str(ledger),
            "--omni-home",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "__" not in run.stdout, "an unexpanded template placeholder"
    plist = tmp_path / "canary.plist"
    plist.write_text(run.stdout)
    lint = subprocess.run(
        ["plutil", "-lint", str(plist)], capture_output=True, text=True, check=False
    )
    assert lint.returncode == 0, lint.stdout + lint.stderr
    assert "--loop" in run.stdout and "<key>KeepAlive</key>" in run.stdout


@pytest.mark.skipif(sys.platform == "darwin", reason="renders the cron line on Linux")
def test_installer_renders_a_cron_line_that_cannot_stack_up(tmp_path: Path) -> None:
    run = subprocess.run(
        ["bash", str(_INSTALLER), "--dry-run", "--state-dir", str(tmp_path / "state")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert (
        run.stdout.startswith("* * * * * ")
        and " timeout 50 " in run.stdout
        and "--once" in run.stdout
    )
