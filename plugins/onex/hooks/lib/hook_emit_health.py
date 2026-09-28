#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Liveness of the hook-emit delivery path, read from the path that delivers.

OMN-18471 AC4. The alert this module replaces read
``${ONEX_STATE_DIR}/hooks/logs/emit-health/status-<event_type>`` -- the
consecutive-failure counters written by ``emit_via_daemon`` in
``scripts/common.sh``, which speaks to a Unix socket at ``~/.claude/emit.sock``.
That socket has not existed since 2026-06-08. Read live on 2026-09-16 the
counters said ``tool.executed`` had failed 101,009 consecutive times with a
last success in June, and they said exactly that whether the real delivery
path was healthy or dead. During the 22-hour drainer outage of 2026-09-15/16
they produced no signal of their own, because they are not connected to the
thing that broke.

What actually delivers a hook event, since OMN-17224, is:

    hook script -> hook_emit_append.py -> ${ONEX_STATE_DIR}/hook_emit_journal
                -> hook_emit_drainer.py (launchd singleton) -> the declared lane

so this module reads exactly two facts off that path and nothing else:

* **backlog depth** -- how many records are sitting in the journal directory;
* **drainer state** -- the status file ``hook_emit_drainer.py`` rewrites on
  every cycle, carrying the timestamp of its last CONFIRMED publish.

Neither fact is inferable from the other, and that is the point. A drainer
that is running but cannot publish leaves a rising backlog with a frozen
``last_publish_at``; a drainer that is dead leaves a rising backlog with a
frozen ``last_cycle_at``. The retired counters could distinguish neither
case from the other, nor either from a healthy machine.

Deliberately stdlib-only, like its siblings on this path: it is evaluated
from a hook script, and a liveness check that pays a multi-second import to
decide whether telemetry is flowing is a cost the operator's session pays
for nothing.

The alerting boundary, stated rather than left implicit
------------------------------------------------------
An absent or stale drainer is reported as ALERTING only while records are
actually queued behind it. A machine with an empty journal and no drainer is
not losing anything, and alerting there would fire on every CI runner and
every collaborator checkout -- noise that trains the reader to ignore the
channel, which is how the counters became useless in the first place. The
harm this alert names is "records are queued and nothing is draining them",
and that is the condition it fires on. The 2026-09-15/16 outage satisfies it:
the journal stood at its 50,000-record bound for 22 hours.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# A drainer that has not completed a cycle in this long, while records are
# queued, is not draining. The drainer's own idle poll is 5s and its error
# backoff 30s, so this is two orders of magnitude above normal cadence and
# cannot fire on an ordinary slow cycle.
DEFAULT_MAX_SILENCE_SECONDS = 900.0

# The journal's own bound is hook_emit_journal.DEFAULT_MAX_RECORDS; at that
# depth the append path has begun DROPPING the oldest records, so telemetry
# is being lost rather than merely delayed. Alert well before that.
DEFAULT_MAX_BACKLOG = 2_000

STATUS_FILENAME = "hook_emit_drainer_status.json"


class EnumHookEmitHealth:
    """Verdict vocabulary. Not a StrEnum -- this module stays stdlib-light."""

    OK = "ok"
    BACKLOG_NOT_DRAINING = "backlog_not_draining"
    DRAINER_SILENT = "drainer_silent"
    DRAINER_STATE_ABSENT = "drainer_state_absent"


@dataclass(frozen=True)
class ModelDrainerStatus:
    """What the drainer last reported about itself.

    ``last_publish_at`` is ``None`` until the drainer confirms its first
    publish, which is a different fact from "published a moment ago" and is
    kept distinguishable on purpose.
    """

    last_cycle_at: float
    last_publish_at: float | None
    published_total: int
    pid: int
    #: OMN-19551: the event types the drainer's LOADED emit registry declares,
    #: i.e. what this drainer can actually publish. ``None`` means the drainer
    #: did not say (an older drainer, or a registry it could not read), which a
    #: producer must read as "not publishable": a record the drainer cannot
    #: resolve blocks the journal head until it is dead-lettered (OMN-19074).
    publishable_event_types: tuple[str, ...] | None = None

    def to_json(self) -> str:
        body: dict[str, object] = {
            "last_cycle_at": self.last_cycle_at,
            "last_publish_at": self.last_publish_at,
            "published_total": self.published_total,
            "pid": self.pid,
        }
        if self.publishable_event_types is not None:
            body["publishable_event_types"] = list(self.publishable_event_types)
        return json.dumps(body, sort_keys=True)


@dataclass(frozen=True)
class ModelHookEmitHealth:
    """One verdict about the live delivery path."""

    verdict: str
    alerting: bool
    depth: int
    drainer_silent_seconds: float | None
    last_publish_age_seconds: float | None
    detail: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "verdict": self.verdict,
                "alerting": self.alerting,
                "journal_depth": self.depth,
                "drainer_silent_seconds": self.drainer_silent_seconds,
                "last_publish_age_seconds": self.last_publish_age_seconds,
                "detail": self.detail,
            },
            sort_keys=True,
        )


def default_state_dir() -> Path:
    """``ONEX_STATE_DIR``, or the documented default beside ``$HOME``."""
    raw = os.environ.get("ONEX_STATE_DIR")
    return Path(raw) if raw else Path.home() / ".onex_state"


def default_journal_dir() -> Path:
    return default_state_dir() / "hook_emit_journal"


def default_status_path() -> Path:
    return default_state_dir() / STATUS_FILENAME


def journal_depth(journal_dir: Path) -> int:
    """Count queued records. An unreadable directory counts as zero.

    A directory that cannot be listed is not evidence of a backlog, and
    guessing one would alert on a machine that has no journal at all.
    """
    try:
        return sum(1 for entry in journal_dir.iterdir() if entry.suffix == ".json")
    except OSError:
        return 0


def write_status(path: Path, status: ModelDrainerStatus) -> None:
    """Atomically rewrite the drainer status file.

    Atomic because the reader is a hook on the operator's session path: a
    torn read would be reported as a malformed status, which this module
    treats as "no state", which would alert. Write-then-rename makes that
    unrepresentable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(status.to_json(), encoding="utf-8")
    tmp.replace(path)


def read_status(path: Path) -> ModelDrainerStatus | None:
    """Read the drainer status, or ``None`` when there is no usable one.

    Absent, unreadable, non-JSON, wrong-shaped and non-numeric all collapse
    to ``None`` -- they are the same fact for this caller ("the drainer is
    not telling us anything"), and a partially-trusted status is worse than
    no status because it reads as evidence.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        last_cycle_at = float(raw["last_cycle_at"])
        published_total = int(raw["published_total"])
        pid = int(raw["pid"])
    except (KeyError, TypeError, ValueError):
        return None
    last_publish_raw = raw.get("last_publish_at")
    try:
        last_publish_at = None if last_publish_raw is None else float(last_publish_raw)
    except (TypeError, ValueError):
        return None
    types_raw = raw.get("publishable_event_types")
    publishable = (
        tuple(t for t in types_raw if isinstance(t, str))
        if isinstance(types_raw, list)
        else None
    )
    return ModelDrainerStatus(
        last_cycle_at=last_cycle_at,
        last_publish_at=last_publish_at,
        published_total=published_total,
        pid=pid,
        publishable_event_types=publishable,
    )


def evaluate(
    *,
    depth: int,
    status: ModelDrainerStatus | None,
    now: float,
    max_backlog: int = DEFAULT_MAX_BACKLOG,
    max_silence_seconds: float = DEFAULT_MAX_SILENCE_SECONDS,
) -> ModelHookEmitHealth:
    """Decide whether the hook-emit path is delivering.

    Pure: every input is a parameter, so the negative case ("the drainer is
    stopped") is a value a test can construct rather than a machine state a
    test would have to produce.
    """
    silent_for = None if status is None else max(0.0, now - status.last_cycle_at)
    publish_age = (
        None
        if status is None or status.last_publish_at is None
        else max(0.0, now - status.last_publish_at)
    )

    if depth <= 0:
        return ModelHookEmitHealth(
            verdict=EnumHookEmitHealth.OK,
            alerting=False,
            depth=depth,
            drainer_silent_seconds=silent_for,
            last_publish_age_seconds=publish_age,
            detail="journal empty; nothing is queued behind the drainer",
        )

    if status is None:
        return ModelHookEmitHealth(
            verdict=EnumHookEmitHealth.DRAINER_STATE_ABSENT,
            alerting=True,
            depth=depth,
            drainer_silent_seconds=None,
            last_publish_age_seconds=None,
            detail=(
                f"{depth} hook event(s) queued and the drainer has reported no "
                f"state at all -- it is not running, or it has never completed "
                f"a cycle on this machine"
            ),
        )

    if silent_for is not None and silent_for > max_silence_seconds:
        return ModelHookEmitHealth(
            verdict=EnumHookEmitHealth.DRAINER_SILENT,
            alerting=True,
            depth=depth,
            drainer_silent_seconds=silent_for,
            last_publish_age_seconds=publish_age,
            detail=(
                f"{depth} hook event(s) queued and the drainer last completed a "
                f"cycle {silent_for:.0f}s ago (bound {max_silence_seconds:.0f}s)"
            ),
        )

    if depth >= max_backlog:
        return ModelHookEmitHealth(
            verdict=EnumHookEmitHealth.BACKLOG_NOT_DRAINING,
            alerting=True,
            depth=depth,
            drainer_silent_seconds=silent_for,
            last_publish_age_seconds=publish_age,
            detail=(
                f"{depth} hook event(s) queued at or above the alert bound "
                f"{max_backlog}; the drainer is cycling but not clearing the "
                f"backlog"
            ),
        )

    return ModelHookEmitHealth(
        verdict=EnumHookEmitHealth.OK,
        alerting=False,
        depth=depth,
        drainer_silent_seconds=silent_for,
        last_publish_age_seconds=publish_age,
        detail=f"{depth} record(s) queued, drainer cycling",
    )


def probe(
    *,
    journal_dir: Path | None = None,
    status_path: Path | None = None,
    now: float | None = None,
    max_backlog: int = DEFAULT_MAX_BACKLOG,
    max_silence_seconds: float = DEFAULT_MAX_SILENCE_SECONDS,
) -> ModelHookEmitHealth:
    """Read the two live facts and evaluate them."""
    jdir = journal_dir if journal_dir is not None else default_journal_dir()
    spath = status_path if status_path is not None else default_status_path()
    return evaluate(
        depth=journal_depth(jdir),
        status=read_status(spath),
        now=time.time() if now is None else now,
        max_backlog=max_backlog,
        max_silence_seconds=max_silence_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    """Print the verdict as JSON. Exit 1 when alerting, 0 otherwise."""
    parser = argparse.ArgumentParser(description="Hook-emit delivery liveness.")
    parser.add_argument("--journal-dir", default=None)
    parser.add_argument("--status-path", default=None)
    parser.add_argument("--max-backlog", type=int, default=DEFAULT_MAX_BACKLOG)
    parser.add_argument(
        "--max-silence-seconds", type=float, default=DEFAULT_MAX_SILENCE_SECONDS
    )
    parser.add_argument(
        "--message",
        action="store_true",
        help="Print the human-readable detail line instead of JSON.",
    )
    args = parser.parse_args(argv)

    result = probe(
        journal_dir=Path(args.journal_dir) if args.journal_dir else None,
        status_path=Path(args.status_path) if args.status_path else None,
        max_backlog=args.max_backlog,
        max_silence_seconds=args.max_silence_seconds,
    )
    print(result.detail if args.message else result.to_json())
    return 1 if result.alerting else 0


if __name__ == "__main__":
    sys.exit(main())
