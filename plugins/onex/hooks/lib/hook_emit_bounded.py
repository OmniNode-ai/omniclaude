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

Stdlib only, like every module on the hook fast path.

Usage::

    hook_emit_bounded.py --label tool.executed --log LOG [--budget S] -- CMD [ARG...]

The runner's stdin is handed to CMD unchanged.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_journal as journal  # noqa: E402

BLOCKING_EXIT = 2
# Operator 2026-09-29 ~20:08Z: 30s, to be titrated from the visible timeout errors.
DEFAULT_BUDGET_S = 30.0
ALARM_BUDGET_S = 8.0
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

    ``alert_channel_send`` posts through the Slack bot token when one is
    configured and records a delivery failure (with its own local
    notification) when the channel is configured but dead. The macOS
    notification is sent regardless, so the operator at the console is told
    even when Slack is not configured on this host.
    """
    alert_sh = Path(__file__).resolve().parent.parent / "scripts" / "alert-channel.sh"
    script = (
        # Exit status is the Slack outcome: 0 delivered, 1 configured but
        # dead, 2 not configured. The runner reports any non-zero on the
        # blocking error, so an alarm that reached only the console says so.
        "rc=3\n"
        'source "$1" 2>/dev/null || true\n'
        "if declare -F alert_channel_send >/dev/null 2>&1; then\n"
        '  alert_channel_send "$2" "$3"; rc=$?\n'
        "fi\n"
        "if [[ -x /usr/bin/osascript ]]; then\n"
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


def _run_bounded(cmd: list[str], budget_s: float) -> tuple[bool, int | None]:
    """Run ``cmd`` in its own process group. Returns (timed_out, returncode).

    Never blocks past the budget: on a miss the group is SIGKILLed and the
    child is left for init to reap once its syscall returns.
    """
    global _last_pgid
    proc = subprocess.Popen(cmd, start_new_session=True)  # noqa: S603
    _last_pgid = proc.pid
    _live_groups.add(proc.pid)
    try:
        return _poll_until(proc, budget_s)
    finally:
        _live_groups.discard(proc.pid)


def _poll_until(
    proc: subprocess.Popen[bytes], budget_s: float
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


def raise_alarm_once(category: str, text: str, marker: Path | None = None) -> bool:
    """Raise the operator alarm if this failure opens an episode.

    The episode marker is created with O_EXCL, so of any number of concurrent
    failing hooks exactly one raises the alarm. Returns True when it did.
    """
    if marker is None:
        marker = episode_marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
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
        print(
            "hook_emit_bounded: operator alarm NOT delivered to Slack "
            f"({'timeout' if timed_out else f'exit {rc}'}; 1=channel dead, "
            "2=not configured); local notification attempted",
            file=sys.stderr,
        )
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
