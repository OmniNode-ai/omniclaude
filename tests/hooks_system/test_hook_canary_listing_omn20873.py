# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The canary's process listing is bounded, and a listing timeout is typed (OMN-20873).

On the loaded operator Mac the canary's single ``ps -axwwo pid,ppid,uid,command``
over every process of every user timed out after 30 seconds, so every run raised
``state=ALERT kinds=canary-error`` with every count NA (six times in the ledger).

The contract tested here:

* the listing reads only the user's own processes, without the command column
  (``ps -x -U <uid>``), asks ``pgrep`` which of them are hook processes, and
  reads the command of exactly those pids (``ps -p``); no call lists every
  process of every user with its command line;
* one deadline bounds all the calls together, so the listing cannot outlive the
  timeout the canary already had;
* a listing that times out is a typed ``ListingTimeout`` (class ``canary-error``
  plus the timeout in seconds), which the notification, ``ALERT.json`` and the
  ledger row state; the ledger row is ``state=CANARY-ERROR``, never
  ``state=ALERT`` with NA counts;
* the real thresholds still alarm on a real reading.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from tests.hooks_system._harness import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "hook_process_canary", REPO_ROOT / "scripts" / "hook_process_canary.py"
)
assert _SPEC is not None and _SPEC.loader is not None
canary = importlib.util.module_from_spec(_SPEC)
sys.modules["hook_process_canary"] = canary
_SPEC.loader.exec_module(canary)

NOW = 1_790_000_000.0
UID = os.getuid()

_HOOK_CMD = "/bin/bash /x/plugins/onex/hooks/scripts/claude_hook_capture.sh"


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fake_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ps_body: str) -> Path:
    """Put a fake ``ps`` and ``pgrep`` first on PATH; ``ps`` logs every argv line."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _script(
        bin_dir / "ps",
        f'echo "ps $*" >> {log}\n{ps_body}\n',
    )
    _script(
        bin_dir / "pgrep",
        f'echo "pgrep $*" >> {log}\necho 4002\necho 4003\n',
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


_PS_OK = f"""
case "$*" in
  *" -p "*)
    echo "4002 1 {UID} {_HOOK_CMD}"
    echo "4003 4000 {UID} {_HOOK_CMD}"
    ;;
  *)
    echo "100 1 {UID}"
    echo "4002 1 {UID}"
    echo "4003 4000 {UID}"
    echo "4004 1 {UID}"
    ;;
esac
"""


def test_hook_process_canary_bounded_listing_never_lists_every_users_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _fake_tools(tmp_path, monkeypatch, _PS_OK)
    rows, _limit = canary.default_sampler()
    calls = log.read_text().splitlines()

    assert not any("-a" in c.split() or "-axwwo" in c for c in calls), calls
    ps_calls = [c for c in calls if c.startswith("ps ")]
    # Exactly one ps over the user's own processes, and it carries no command column.
    cheap = [c for c in ps_calls if "-p" not in c.split()]
    assert len(cheap) == 1 and f"-U {UID}" in cheap[0] and "command" not in cheap[0]
    # The command is read only for the pids pgrep selected.
    selected = [c for c in ps_calls if "-p" in c.split()]
    assert len(selected) == 1 and "4002,4003" in selected[0]
    assert any(c.startswith("pgrep ") and f"-U {UID}" in c for c in calls)

    by_pid = {r.pid: r for r in rows}
    assert set(by_pid) == {100, 4002, 4003, 4004}
    assert by_pid[4002].command == _HOOK_CMD and by_pid[4002].ppid == 1
    assert by_pid[100].command == ""


def test_hook_process_canary_bounded_listing_keeps_the_same_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_tools(tmp_path, monkeypatch, _PS_OK)
    rows, _ = canary.default_sampler()
    reading = canary.measure(rows, uid=UID, limit=None, self_pid=1)
    assert reading.hook_processes == 2
    assert reading.hook_orphans == 1  # only 4002 is parented to pid 1 AND a hook
    assert reading.user_processes == 4


def test_hook_process_canary_bounded_listing_no_hook_processes_is_a_clean_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "ps", f'echo "100 1 {UID}"\n')
    _script(bin_dir / "pgrep", "exit 1\n")  # pgrep exits 1 when nothing matches
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    rows, _ = canary.default_sampler()
    reading = canary.measure(rows, uid=UID, limit=None, self_pid=1)
    assert (reading.hook_processes, reading.user_processes) == (0, 1)


def test_hook_process_canary_bounded_listing_one_deadline_bounds_every_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two calls that each take 0.7 s fit a 1 s budget one at a time, not together."""
    monkeypatch.setattr(canary, "_SUBPROCESS_TIMEOUT_S", 1)
    _fake_tools(tmp_path, monkeypatch, f"sleep 0.7\n{_PS_OK}")
    with pytest.raises(canary.ListingTimeoutError) as caught:
        canary.default_sampler()
    assert caught.value.result.timeout_seconds == 1


# ---------------------------------------------------------------------------
# A listing timeout is typed
# ---------------------------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.rows: list[str] = []

    def notify(self, title: str, message: str) -> bool:
        self.notifications.append((title, message))
        return True

    def ledger(self, row: str) -> bool:
        self.rows.append(row)
        return True


def _timing_out_canary(tmp_path: Path, sink: _Sink) -> canary.Canary:
    def sampler() -> tuple[list[canary.ProcRow], int | None]:
        raise canary.ListingTimeoutError(
            canary.ListingTimeout(
                error_class="canary-error", timeout_seconds=30, command="ps"
            )
        )

    return canary.Canary(
        state_dir=tmp_path,
        thresholds=canary.Thresholds(),
        sampler=sampler,
        notify=sink.notify,
        append_ledger=sink.ledger,
        uid=UID,
        host="testhost",
        interval_seconds=60,
    )


def test_hook_process_canary_listing_timeout_typed_is_canary_error_not_alert(
    tmp_path: Path,
) -> None:
    sink = _Sink()
    result = _timing_out_canary(tmp_path, sink).run_once(NOW)

    assert [a.kind for a in result.alarms] == ["canary-error"]
    assert result.reading is None and result.delivered

    row = sink.rows[0]
    assert " | STATUS | lane=hook-process-canary | " in row
    assert "state=CANARY-ERROR" in row and "state=ALERT" not in row
    assert "class=canary-error" in row and "timeout_s=30" in row
    assert "command=ps" in row
    assert "=NA" not in row  # no count is invented for a measurement that did not run

    title, message = sink.notifications[0]
    assert "canary-error" in title and "30 seconds" in message


def test_hook_process_canary_listing_timeout_typed_lands_in_alert_json(
    tmp_path: Path,
) -> None:
    _timing_out_canary(tmp_path, _Sink()).run_once(NOW)
    alert = json.loads((tmp_path / "ALERT.json").read_text())
    assert alert["kinds"] == ["canary-error"]
    assert alert["listing_timeout"] == {
        "error_class": "canary-error",
        "timeout_seconds": 30,
        "command": "ps",
    }


def test_hook_process_canary_listing_timeout_typed_real_ps_that_hangs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lab proof in miniature: a planted slow ps, the real sampler."""
    monkeypatch.setattr(canary, "_SUBPROCESS_TIMEOUT_S", 1)
    _fake_tools(tmp_path, monkeypatch, "sleep 5")
    sink = _Sink()
    c = canary.Canary(
        state_dir=tmp_path / "state",
        thresholds=canary.Thresholds(),
        sampler=canary.default_sampler,
        notify=sink.notify,
        append_ledger=sink.ledger,
        uid=UID,
        host="testhost",
        interval_seconds=60,
    )
    result = c.run_once(NOW)
    assert [a.kind for a in result.alarms] == ["canary-error"]
    row = sink.rows[0]
    assert "state=CANARY-ERROR" in row and "timeout_s=1" in row and "=NA" not in row


def test_hook_process_canary_listing_timeout_typed_does_not_hide_a_real_alarm(
    tmp_path: Path,
) -> None:
    """A real reading still raises ALERT with its counts; only a missing one differs."""
    sink = _Sink()
    rows = [
        canary.ProcRow(i, 1, UID, _HOOK_CMD) for i in range(1, 30)
    ]  # 29 orphaned hooks, above the 20 max
    c = canary.Canary(
        state_dir=tmp_path,
        thresholds=canary.Thresholds(),
        sampler=lambda: (rows, None),
        notify=sink.notify,
        append_ledger=sink.ledger,
        uid=UID,
        host="testhost",
        interval_seconds=60,
        self_pid=999_999,
    )
    c.run_once(NOW)
    assert "state=ALERT" in sink.rows[0] and "orphans=29" in sink.rows[0]
