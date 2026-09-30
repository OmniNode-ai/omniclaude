#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Run one hook emit inside a time budget, and fail loud when it misses (OMN-20110).

On 2026-09-29 the per-user process limit on the operator Mac was exhausted by
about ten thousand hook processes: emitters stuck in a whole-journal directory
scan, each forked into the background and disowned by its hook, so each one
was orphaned to ppid 1 and nothing reported it. The operator ruling that
followed, the same day: a hook may not fail silently, and an emit that cannot
complete must stop the work and raise an alarm rather than take an alternate
path.

This runner is that policy, in one place:

* The emitter runs in the FOREGROUND, in its own session and process group.
* It gets ``--budget`` seconds. On a miss, the runner SIGKILLs the whole
  process group and exits without waiting for it, because a process in
  uninterruptible wait cannot be reaped until its syscall returns, and
  waiting on it is how the hook itself would hang.
* Any failure (a miss, or the emitter exiting non-zero) exits
  :data:`BLOCKING_EXIT` with a message on stderr that names the cause. Claude
  Code treats exit 2 as a blocking error, so the tool call fails and both the
  agent and the operator see why.
* The first failure of an episode raises the operator alarm, once. A later
  successful emit closes the episode, so the next failure alarms again.

There is no spool, no fail-open branch and no kill switch here, by ruling.

A writer in this directory runs in a FORKED child, not a second interpreter
(OMN-20118). The hooks pass ``<python> <this dir>/<writer>.py ARG...``; every
such writer is a stdlib script of this directory, so the runner forks, the
child runs the script as ``__main__`` with that argv, and exits with its code.
The interpreter start and the shared imports are paid once instead of twice
per emit, which was about half of every tool call's interpreter starts. The
child is its own process group exactly as an exec'd emitter was, so the
budget, the group kill, the blocking exit and the alarm are unchanged. Any
other command (a test's ``/usr/bin/false``, the alarm) is still exec'd.

Stdlib only, like every module on the hook fast path.

Usage::

    hook_emit_bounded.py --label tool.executed --log LOG [--budget S] -- CMD [ARG...]

The runner's stdin is handed to CMD unchanged.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import runpy
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_journal as journal  # noqa: E402

BLOCKING_EXIT = 2
# Operator 2026-09-29 ~20:08Z: 30s, to be titrated from the visible timeout errors.
DEFAULT_BUDGET_S = 30.0
ALARM_BUDGET_S = 8.0
# An alarm that reached no Slack channel is retried after this long, so a
# channel that is down for a minute does not swallow the whole episode.
ALARM_RETRY_S = 300.0
_UNDELIVERED = "UNDELIVERED"
_LEDGER_APPEND_TIMEOUT_S = 10.0
_TAIL_BYTES = 600
_EPISODE_MARKER = "hook_emit_failure_episode"


def _state_dir() -> Path:
    """The state directory the journal lives in, resolved the journal's way."""
    return journal.default_journal_dir().parent


def episode_marker_path() -> Path:
    override = os.environ.get("ONEX_EMIT_EPISODE_MARKER")
    if override:
        return Path(override)
    return _state_dir() / "hooks" / _EPISODE_MARKER


def _default_alarm_cmd(category: str, text: str) -> list[str]:
    """The existing alerting path: alert-channel.sh, plus a local notification.

    ``alert_channel_alarm`` resolves the Slack bot token and channel from the
    environment or, failing that, by reading the one operator env file (the
    launchd drainer and cron canary inherit neither, OMN-20109), and posts
    through the Slack Web API. An unresolvable credential or a dead channel
    is a recorded delivery failure and a non-zero exit; "not configured" is
    not a quiet outcome for an alarm. The macOS notification is sent
    regardless, so the operator at the console is told even then.
    """
    alert_sh = Path(__file__).resolve().parent.parent / "scripts" / "alert-channel.sh"
    script = (
        # Exit status is the Slack outcome: 0 delivered, non-zero not
        # delivered. The runner reports any non-zero on the blocking error,
        # raises a ledger ALERT row, and retries the episode later.
        "rc=3\n"
        'source "$1" 2>/dev/null || true\n'
        "if declare -F alert_channel_alarm >/dev/null 2>&1; then\n"
        '  alert_channel_alarm "$2" "$3"; rc=$?\n'
        "fi\n"
        'if [[ -n "${ONEX_ALERT_LOCAL_NOTIFY_CMD:-}" ]]; then\n'
        '  "${ONEX_ALERT_LOCAL_NOTIFY_CMD}" "$3" >/dev/null 2>&1 || true\n'
        "elif [[ -x /usr/bin/osascript ]]; then\n"
        "  esc=$(printf '%s' \"$3\" | sed -e 's/\\\\/\\\\\\\\/g' -e 's/\"/\\\\\"/g')\n"
        '  /usr/bin/osascript -e "display notification \\"${esc}\\" with title '
        '\\"Hook emit FAILED - work is blocked\\" sound name \\"Sosumi\\"" '
        ">/dev/null 2>&1 || true\n"
        "fi\n"
        "exit $rc\n"
    )
    return ["/bin/bash", "-c", script, "hook-emit-alarm", str(alert_sh), category, text]


def _alarm_cmd(category: str, text: str) -> list[str]:
    override = os.environ.get("ONEX_EMIT_ALARM_CMD")
    if override:
        return [override, category, text]
    return _default_alarm_cmd(category, text)


_live_groups: set[int] = set()


def _on_signal(signum: int, _frame: object) -> None:
    """The hook itself is being cancelled: take every emitter group with it.

    The emitter runs in its own session, so a harness that kills the hook's
    process group would otherwise leave it running with nobody enforcing its
    budget -- the orphan this module exists to prevent.
    """
    for pgid in list(_live_groups):
        _kill_group(pgid)
    os._exit(128 + signum)


def _install_signal_handlers() -> None:
    """Installed by :func:`main` only, so the drainer can import this module
    for :func:`raise_alarm_once` without having its own handlers replaced."""
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _on_signal)


_last_pgid = 0


_LIB_DIR = Path(__file__).resolve().parent


def in_process_writer(cmd: list[str]) -> Path | None:
    """The writer script ``cmd`` runs, when it is ``<python> <lib>/<writer>.py ...``.

    Only a ``.py`` file in this module's own directory qualifies: those are the
    stdlib journal writers the hooks call. Anything else is exec'd as before.
    """
    if len(cmd) < 2 or "python" not in Path(cmd[0]).name:
        return None
    script = Path(cmd[1])
    if script.suffix != ".py":
        return None
    try:
        resolved = script.resolve()
    except OSError:
        return None
    if resolved.parent != _LIB_DIR or not resolved.is_file():
        return None
    return resolved


def _exit_code(code: object) -> int:
    """``SystemExit.code`` as the process exit status the interpreter would use."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code & 0xFF
    print(code, file=sys.stderr)
    return 1


def _run_writer_in_child(script: Path, args: list[str]) -> int:
    """Body of the forked child: run ``script`` as ``__main__``; return its code."""
    with contextlib.suppress(OSError):
        # Already a group leader when the parent's setpgid won the race.
        os.setsid()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_DFL)
    sys.argv = [str(script), *args]
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as exc:
        return _exit_code(exc.code)
    return 0


class _ForkedWriter:
    """A forked writer, with the two parts of ``Popen`` the budget loop uses."""

    def __init__(self, script: Path, args: list[str]) -> None:
        for stream in (sys.stdout, sys.stderr):
            with contextlib.suppress(Exception):
                stream.flush()
        pid = os.fork()
        if pid == 0:
            code = 1
            try:
                code = _run_writer_in_child(script, args)
            except BaseException:  # noqa: BLE001 -- the child's outermost frame
                with contextlib.suppress(Exception):
                    traceback.print_exc()
            finally:
                for stream in (sys.stdout, sys.stderr):
                    with contextlib.suppress(Exception):
                        stream.flush()
                os._exit(code)
        # Both sides set the group, so it is a group of its own before the
        # budget starts whichever runs first (the setsid-or-setpgid idiom).
        with contextlib.suppress(OSError):
            os.setpgid(pid, pid)
        self.pid = pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is None:
            try:
                done, status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                self.returncode = 1
                return self.returncode
            if done:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode


def _run_bounded(cmd: list[str], budget_s: float) -> tuple[bool, int | None]:
    """Run ``cmd`` in its own process group. Returns (timed_out, returncode).

    Never blocks past the budget: on a miss the group is SIGKILLed and the
    child is left for init to reap once its syscall returns.
    """
    global _last_pgid
    script = in_process_writer(cmd)
    proc: _ForkedWriter | subprocess.Popen[bytes]
    if script is not None:
        proc = _ForkedWriter(script, cmd[2:])
    else:
        proc = subprocess.Popen(cmd, start_new_session=True)  # noqa: S603
    _last_pgid = proc.pid
    _live_groups.add(proc.pid)
    try:
        return _poll_until(proc, budget_s)
    finally:
        _live_groups.discard(proc.pid)


def _poll_until(
    proc: _ForkedWriter | subprocess.Popen[bytes], budget_s: float
) -> tuple[bool, int | None]:
    deadline = time.monotonic() + budget_s
    while True:
        rc = proc.poll()
        if rc is not None:
            _kill_group(proc.pid)  # grandchildren the emitter left behind
            return False, rc
        if time.monotonic() >= deadline:
            _kill_group(proc.pid)
            return True, None
        time.sleep(0.01)


def _kill_group(pgid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)


def _cell(text: str) -> str:
    """One ledger cell: no pipe, no newline."""
    return " ".join(text.replace("|", "/").split())


def _ledger_paths() -> tuple[Path, Path] | None:
    """The rolling ledger and its locked-append script, or None when unknown.

    ``ONEX_LEDGER_PATH`` and ``ONEX_LEDGER_LOCK_SCRIPT`` when set (the canary
    plist sets them). The launchd drainer sets neither, so they fall back to
    the fixed locations under the workspace root, which is the parent of the
    required ``ONEX_STATE_DIR`` (the drainer's environment carries that
    variable and no ledger variable). No state dir, no guess.
    """
    ledger = os.environ.get("ONEX_LEDGER_PATH")
    lock = os.environ.get("ONEX_LEDGER_LOCK_SCRIPT")
    state = os.environ.get("ONEX_STATE_DIR")
    home = Path(state).parent if state else None
    if not ledger and home:
        ledger = str(home / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md")
    if not lock and home:
        lock = str(home / "scripts" / "ledger_lock.py")
    if not ledger or not lock:
        return None
    return Path(ledger), Path(lock)


def record_undelivered_alarm(category: str, text: str, why: str) -> bool:
    """Write a ledger STATUS state=ALERT row for an alarm Slack never received.

    The operator ruling of 2026-09-29: an alarm path that cannot alarm must
    fail loud, not print a line nobody reads. This is the durable half (the
    macOS notification and the non-zero exit are the other two). Returns True
    when the row was appended; on False the reason is on stderr.
    """
    paths = _ledger_paths()
    if paths is None:
        print(
            "hook_emit_bounded: cannot record the undelivered alarm in the ledger: "
            "set ONEX_LEDGER_PATH and ONEX_LEDGER_LOCK_SCRIPT (or ONEX_STATE_DIR)",
            file=sys.stderr,
        )
        return False
    ledger, lock = paths
    row = (
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} | STATUS | "
        f"lane=hook-emit-alarm | state=ALERT | host={_cell(os.uname().nodename)} | "
        f"category={_cell(category)} | slack-delivery={_cell(why)} | "
        f"detail={_cell(text)[:400]}"
    )
    try:
        done = subprocess.run(  # noqa: S603
            [
                sys.executable,
                str(lock),
                str(ledger),
                "--timeout",
                "5s",
                "--append",
                row,
            ],
            capture_output=True,
            text=True,
            timeout=_LEDGER_APPEND_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"hook_emit_bounded: ledger ALERT append failed: {exc}", file=sys.stderr)
        return False
    if done.returncode != 0:
        print(
            f"hook_emit_bounded: ledger ALERT append exited {done.returncode}: "
            f"{done.stderr.strip()[:300]}",
            file=sys.stderr,
        )
        return False
    return True


def _marker_retry_due(marker: Path) -> bool:
    """True when the marker records an UNDELIVERED alarm old enough to retry."""
    try:
        age = time.time() - marker.stat().st_mtime
        with marker.open("rb") as fh:
            head = fh.read(4096)
    except OSError:
        return False
    return _UNDELIVERED.encode() in head and age >= ALARM_RETRY_S


def _write_marker(marker: Path, text: str, *, delivered: bool) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    flag = "" if delivered else f"{_UNDELIVERED} "
    with contextlib.suppress(OSError):
        marker.write_text(f"{stamp} {flag}{text}\n")


def raise_alarm_once(category: str, text: str, marker: Path | None = None) -> bool:
    """Raise the operator alarm if this failure opens an episode.

    The episode marker is created with O_EXCL, so of any number of concurrent
    failing hooks exactly one raises the alarm. Returns True when it did.

    An alarm that Slack did not receive (an unresolvable credential, a dead
    channel, a timeout) is never silent: it prints on stderr, appends a ledger
    STATUS state=ALERT row, leaves the local notification the alarm command
    always raises, and marks the episode UNDELIVERED so it is raised again
    after :data:`ALARM_RETRY_S` instead of being swallowed for good.
    """
    if marker is None:
        marker = episode_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        if not _marker_retry_due(marker):
            return False
        fd = -1
        with contextlib.suppress(OSError):
            os.utime(marker)  # claim this retry: concurrent failers see a fresh clock
    except OSError as exc:
        # Cannot record the episode: alarm anyway. Over-alarming is the safe
        # direction for a failure the operator ruled must never be silent.
        print(f"hook_emit_bounded: episode marker unwritable ({exc})", file=sys.stderr)
        fd = -1
    if fd >= 0:
        with contextlib.suppress(OSError):
            os.write(
                fd,
                f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {text}\n".encode(),
            )
            os.close(fd)
    timed_out, rc = _run_bounded(_alarm_cmd(category, text), ALARM_BUDGET_S)
    if timed_out or rc:
        why = "timeout" if timed_out else f"exit {rc}"
        print(
            f"hook_emit_bounded: operator alarm NOT delivered to Slack ({why}); "
            "local notification attempted, ledger ALERT row requested",
            file=sys.stderr,
        )
        _write_marker(marker, text, delivered=False)
        record_undelivered_alarm(category, text, why)
    else:
        _write_marker(marker, text, delivered=True)
    return True


def close_episode(marker: Path | None = None) -> None:
    with contextlib.suppress(FileNotFoundError, OSError):
        (marker if marker is not None else episode_marker_path()).unlink()


def _tail(log: Path | None, start: int) -> str:
    if log is None:
        return ""
    try:
        with log.open("rb") as fh:
            fh.seek(max(start, 0))
            data = fh.read()
    except OSError:
        return ""
    text = data[-_TAIL_BYTES:].decode("utf-8", "replace").strip()
    return " | ".join(line for line in text.splitlines() if line.strip())[-_TAIL_BYTES:]


def main(argv: list[str] | None = None) -> int:
    _install_signal_handlers()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("hook_emit_bounded: usage: ... -- CMD [ARG...]", file=sys.stderr)
        return BLOCKING_EXIT
    split = argv.index("--")
    parser = argparse.ArgumentParser(prog="hook_emit_bounded")
    parser.add_argument("--label", required=True)
    parser.add_argument("--log", default=None)
    parser.add_argument(
        "--budget",
        type=float,
        default=float(os.environ.get("ONEX_HOOK_EMIT_BUDGET_S", DEFAULT_BUDGET_S)),
    )
    args = parser.parse_args(argv[:split])
    cmd = argv[split + 1 :]
    if not cmd:
        print("hook_emit_bounded: no command after --", file=sys.stderr)
        return BLOCKING_EXIT

    log = Path(args.log) if args.log else None
    start = 0
    if log is not None:
        with contextlib.suppress(OSError):
            log.parent.mkdir(parents=True, exist_ok=True)
            start = log.stat().st_size if log.exists() else 0

    # The emitter's stdout and stderr go to the hook log, never to the hook's
    # own stdout: a Stop or UserPromptSubmit hook that prints becomes a
    # message the model answers.
    if log is not None:
        try:
            log_fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        except OSError:
            log_fd = os.open(os.devnull, os.O_WRONLY)
    else:
        log_fd = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        started = time.monotonic()
        timed_out, rc = _run_bounded(cmd, args.budget)
        elapsed = time.monotonic() - started
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(saved_out)
        os.close(saved_err)
        os.close(log_fd)

    if not timed_out and rc == 0:
        close_episode()
        return 0

    if timed_out:
        cause = (
            f"did not complete within its {args.budget:g}s budget (killed after "
            f"{elapsed:.1f}s); its process group {_last_pgid} was killed"
        )
    else:
        cause = f"exited {rc} after {elapsed:.1f}s"
    detail = _tail(log, start)
    message = (
        f"BLOCKED: hook emit '{args.label}' {cause}"
        f"{' -- ' + detail if detail else ''}. "
        f"The event was NOT recorded. Fix the emit path (journal "
        f"{journal.default_journal_dir()}, drainer ai.omninode.hook-emit-drainer)"
        f"{', log ' + str(log) if log else ''}. Ticket OMN-20110."
    )
    print(message, file=sys.stderr)
    if log is not None:
        with contextlib.suppress(OSError), log.open("a") as fh:
            fh.write(
                f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {message}\n"
            )
    host = os.uname().nodename
    raise_alarm_once("hook_emit_failed", f"[{host}] {message}")
    return BLOCKING_EXIT


if __name__ == "__main__":
    sys.exit(main())
