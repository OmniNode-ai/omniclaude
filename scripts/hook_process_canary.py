#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Live hook-process canary (OMN-20109).

On 2026-09-29 about 10,000 hung hook processes exhausted the per-user process
limit of the operator Mac and stopped every lane. Nothing counted them. The
suite in ``tests/hooks_system`` proves the hooks behave in CI; this is the live
half. Every ``--interval`` seconds (60 by default) it counts, for the user it
runs as:

* hook processes: commands under ``/hooks/scripts/`` or ``/hooks/lib/``,
* hook processes orphaned to pid 1 (a hook whose parent died and never
  finished is the leak),
* every process the user owns, against the per-user limit
  (``kern.maxprocperuid`` on macOS, ``RLIMIT_NPROC`` on Linux).

Thresholds (each strictly greater raises an alarm): orphans above 20, hook
processes above 150, user processes above 60 percent of the limit.

It never fails silently. A measurement that cannot run (the fork that starts
``ps`` failing is the very state it exists for) is the ``cannot-measure``
alarm, an exception inside it is ``canary-error``, and a gap of more than three
intervals since the last heartbeat is ``canary-gap``. An alarm is delivered once
per episode and kind through the operator notifier and as a ledger STATUS row
with ``state=ALERT``; one that reached neither channel is retried every cycle
and never marked delivered. ``ALERT.json`` is always written first.

Exit codes of ``--once``: 0 healthy, 3 alarm delivered, 4 alarm undelivered,
5 the canary itself failed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import resource
import signal
import socket
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

LANE = "hook-process-canary"
_HOOK_PATH = re.compile(r"/hooks/(scripts|lib)/")
# Resident daemons that live under the hook tree by design, parented to pid 1
# (launchd or init) on purpose. They are not hook invocations and never leaks.
_RESIDENT_DAEMONS = ("hook_emit_drainer.py",)
_GAP_INTERVALS = 3
_SUBPROCESS_TIMEOUT_S = 30


@dataclass(frozen=True)
class ProcRow:
    pid: int
    ppid: int
    uid: int
    command: str


@dataclass(frozen=True)
class Reading:
    hook_processes: int
    hook_pythons: int
    hook_orphans: int
    user_processes: int
    limit: int | None


@dataclass(frozen=True)
class Thresholds:
    orphans_max: int = 20
    hook_procs_max: int = 150
    user_ratio_max: float = 0.6


@dataclass(frozen=True)
class Alarm:
    kind: str
    detail: str


@dataclass
class CycleResult:
    alarms: list[Alarm] = field(default_factory=list)
    delivered: bool = False
    reading: Reading | None = None


Sampler = Callable[[], tuple[list[ProcRow], int | None]]
Notify = Callable[[str, str], bool]
AppendLedger = Callable[[str], bool]


def parse_ps(text: str) -> list[ProcRow]:
    rows: list[ProcRow] = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid, ppid, uid = int(parts[0]), int(parts[1]), int(parts[2])
        except ValueError:
            continue
        rows.append(ProcRow(pid, ppid, uid, parts[3] if len(parts) > 3 else ""))
    return rows


def measure(rows: list[ProcRow], uid: int, limit: int | None, self_pid: int) -> Reading:
    mine = [r for r in rows if r.uid == uid and r.pid != self_pid]
    hooks = [
        r
        for r in mine
        if _HOOK_PATH.search(r.command)
        and not any(daemon in r.command for daemon in _RESIDENT_DAEMONS)
    ]
    return Reading(
        hook_processes=len(hooks),
        hook_pythons=sum(1 for r in hooks if "python" in r.command),
        hook_orphans=sum(1 for r in hooks if r.ppid == 1),
        user_processes=len(mine),
        limit=limit,
    )


def evaluate(reading: Reading, thresholds: Thresholds) -> list[Alarm]:
    alarms: list[Alarm] = []
    if reading.hook_orphans > thresholds.orphans_max:
        alarms.append(
            Alarm(
                "hook-orphans",
                f"{reading.hook_orphans} hook processes orphaned to pid 1 (max {thresholds.orphans_max})",
            )
        )
    if reading.hook_processes > thresholds.hook_procs_max:
        alarms.append(
            Alarm(
                "hook-process-count",
                f"{reading.hook_processes} hook processes alive (max {thresholds.hook_procs_max})",
            )
        )
    if (
        reading.limit is not None
        and reading.user_processes > reading.limit * thresholds.user_ratio_max
    ):
        alarms.append(
            Alarm(
                "user-process-limit",
                f"{reading.user_processes} user processes against a limit of {reading.limit} "
                f"(alarm above {int(thresholds.user_ratio_max * 100)} percent)",
            )
        )
    return alarms


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, sort_keys=True))
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _cell(text: str) -> str:
    """One ledger cell: no pipe, no newline."""
    return " ".join(text.replace("|", "/").split())


class Canary:
    def __init__(
        self,
        state_dir: Path,
        thresholds: Thresholds,
        sampler: Sampler,
        notify: Notify,
        append_ledger: AppendLedger,
        uid: int,
        host: str,
        interval_seconds: float = 60,
        self_pid: int | None = None,
    ) -> None:
        self.state_dir = state_dir
        self.thresholds = thresholds
        self.sampler = sampler
        self.notify = notify
        self.append_ledger = append_ledger
        self.uid = uid
        self.host = host
        self.interval_seconds = interval_seconds
        self.self_pid = os.getpid() if self_pid is None else self_pid

    # -- one cycle ----------------------------------------------------------

    def run_once(self, now: float) -> CycleResult:
        alarms: list[Alarm] = []
        beat = _read_json(self.state_dir / "heartbeat.json")
        last = beat.get("at") if beat else None
        if (
            isinstance(last, (int, float))
            and now - last > _GAP_INTERVALS * self.interval_seconds
        ):
            alarms.append(
                Alarm("canary-gap", f"no canary cycle for {int(now - last)} s")
            )

        reading: Reading | None = None
        try:
            rows, limit = self.sampler()
            reading = measure(rows, self.uid, limit, self.self_pid)
            alarms.extend(evaluate(reading, self.thresholds))
        except OSError as exc:
            alarms.append(Alarm("cannot-measure", f"cannot run ps: {exc}"))
        except (
            Exception
        ) as exc:  # the canary must alarm on its own failure, never skip a cycle
            alarms.append(Alarm("canary-error", f"{type(exc).__name__}: {exc}"))

        _atomic_write(self.state_dir / "heartbeat.json", {"at": now, "host": self.host})

        episode_path = self.state_dir / "episode.json"
        if not alarms:
            episode_path.unlink(missing_ok=True)
            return CycleResult([], False, reading)

        _atomic_write(
            self.state_dir / "ALERT.json",
            {
                "at": now,
                "host": self.host,
                "kinds": sorted(a.kind for a in alarms),
                "alarms": [asdict(a) for a in alarms],
                "reading": asdict(reading) if reading else None,
            },
        )
        episode = _read_json(episode_path) or {}
        raw = episode.get("delivered")
        done: set[str] = (
            {k for k in raw if isinstance(k, str)} if isinstance(raw, list) else set()
        )
        new = [a for a in alarms if a.kind not in done]
        if not new:
            return CycleResult(alarms, True, reading)

        delivered = self._deliver(new, reading, now)
        if delivered:
            _atomic_write(
                episode_path, {"delivered": sorted(done | {a.kind for a in new})}
            )
        return CycleResult(alarms, delivered, reading)

    def _deliver(self, new: list[Alarm], reading: Reading | None, now: float) -> bool:
        kinds = ",".join(a.kind for a in new)
        detail = "; ".join(a.detail for a in new)
        title = f"HOOK CANARY {self.host}: {kinds}"
        message = f"{detail}. See ALERT.json in {self.state_dir}."
        r = reading
        counts = (
            f"orphans={r.hook_orphans} hook_procs={r.hook_processes} hook_pythons={r.hook_pythons} "
            f"user_procs={r.user_processes} limit={r.limit if r.limit is not None else 'NA'}"
            if r
            else "orphans=NA hook_procs=NA hook_pythons=NA user_procs=NA limit=NA"
        )
        ts = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = (
            f"{ts} | STATUS | lane={LANE} | state=ALERT | host={_cell(self.host)} | "
            f"kinds={kinds} | {counts} | detail={_cell(detail)}"
        )
        notify_ok = self._safely(
            lambda: self.notify(_cell(title), _cell(message)), "notify"
        )
        ledger_ok = self._safely(lambda: self.append_ledger(row), "ledger append")
        return notify_ok or ledger_ok

    @staticmethod
    def _safely(call: Callable[[], bool], what: str) -> bool:
        try:
            return bool(call())
        except Exception as exc:
            print(
                f"hook_process_canary: {what} raised {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return False


# -- the real host --------------------------------------------------------------


def _read_limit() -> int | None:
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(
                ["sysctl", "-n", "kern.maxprocperuid"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            return int(out.stdout.strip())
        soft = resource.getrlimit(resource.RLIMIT_NPROC)[0]
        return None if soft == resource.RLIM_INFINITY else int(soft)
    except Exception as exc:
        print(
            f"hook_process_canary: cannot read the per-user process limit: {exc}",
            file=sys.stderr,
        )
        return None


def default_sampler() -> tuple[list[ProcRow], int | None]:
    # A fork failure raises OSError and propagates: the caller alarms on it.
    out = subprocess.run(
        ["ps", "-axwwo", "pid=,ppid=,uid=,command="],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
        check=True,
    )
    return parse_ps(out.stdout), _read_limit()


def _forced_error_sampler() -> tuple[list[ProcRow], int | None]:
    raise RuntimeError("forced canary error")


def _external(cmd: str, what: str) -> Callable[..., bool]:
    def run(*args: str) -> bool:
        try:
            done = subprocess.run(
                [cmd, *args],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(
                f"hook_process_canary: {what} command {cmd} failed: {exc}",
                file=sys.stderr,
            )
            return False
        if done.returncode != 0:
            print(
                f"hook_process_canary: {what} command {cmd} exited {done.returncode}: {done.stderr.strip()[:300]}",
                file=sys.stderr,
            )
        return done.returncode == 0

    return run


def make_notify(cmd: str) -> Notify:
    return _external(cmd, "notify")


def make_ledger(cmd: str) -> AppendLedger:
    return _external(cmd, "ledger append")


def _summary(result: CycleResult) -> str:
    r = result.reading
    counts = (
        f"hook={r.hook_processes} py={r.hook_pythons} orphans={r.hook_orphans} user={r.user_processes} limit={r.limit}"
        if r
        else "reading=none"
    )
    kinds = ",".join(a.kind for a in result.alarms) or "none"
    return f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} canary {counts} alarms={kinds} delivered={result.delivered}"


def _exit_code(result: CycleResult) -> int:
    if not result.alarms:
        return 0
    if any(a.kind == "canary-error" for a in result.alarms):
        return 5
    if not result.delivered:
        kinds = ",".join(a.kind for a in result.alarms)
        print(f"UNDELIVERED: {kinds}", file=sys.stderr)
        return 4
    return 3


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--loop", action="store_true")
    p.add_argument("--interval", type=float, default=60.0)
    p.add_argument("--state-dir", type=Path, default=None)
    p.add_argument("--orphans-max", type=int, default=Thresholds.orphans_max)
    p.add_argument("--hook-procs-max", type=int, default=Thresholds.hook_procs_max)
    p.add_argument("--user-ratio-max", type=float, default=Thresholds.user_ratio_max)
    args = p.parse_args(argv)

    state_dir = args.state_dir
    if state_dir is None:
        base = os.environ.get("ONEX_STATE_DIR")
        if not base:
            print(
                "hook_process_canary: set ONEX_STATE_DIR or pass --state-dir; no default is assumed",
                file=sys.stderr,
            )
            return 2
        state_dir = Path(base) / "hook_canary"

    sampler: Sampler = (
        _forced_error_sampler
        if os.environ.get("HOOK_CANARY_FORCE_ERROR") == "1"
        else default_sampler
    )
    notify_cmd = os.environ.get("HOOK_CANARY_NOTIFY_CMD") or str(
        here / "hook_canary_notify.sh"
    )
    ledger_cmd = os.environ.get("HOOK_CANARY_LEDGER_APPEND_CMD") or str(
        here / "hook_canary_ledger_append.sh"
    )
    canary = Canary(
        state_dir=state_dir,
        thresholds=Thresholds(
            args.orphans_max, args.hook_procs_max, args.user_ratio_max
        ),
        sampler=sampler,
        notify=make_notify(notify_cmd),
        append_ledger=make_ledger(ledger_cmd),
        uid=os.getuid(),
        host=socket.gethostname().split(".")[0],
        interval_seconds=args.interval,
    )

    if args.once:
        result = canary.run_once(time.time())
        print(_summary(result), flush=True)
        return _exit_code(result)

    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    while not stop["now"]:
        started = time.monotonic()
        try:
            print(_summary(canary.run_once(time.time())), flush=True)
        except Exception as exc:
            # A cycle that cannot even record its own state is the canary failing:
            # say so on stderr AND through the operator notifier, never only in a log.
            print("hook_process_canary: cycle failed", file=sys.stderr)
            traceback.print_exc()
            Canary._safely(
                lambda: canary.notify(
                    f"HOOK CANARY {canary.host}: canary-error",
                    _cell(f"the canary cycle failed: {type(exc).__name__}: {exc}"),
                ),
                "notify",
            )
        remaining = args.interval - (time.monotonic() - started)
        end = time.monotonic() + max(remaining, 0.0)
        while not stop["now"] and time.monotonic() < end:
            time.sleep(min(1.0, max(end - time.monotonic(), 0.0)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
