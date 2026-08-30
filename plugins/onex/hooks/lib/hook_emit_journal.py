# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Stdlib-only hook-emit journal: the fast half of the OMN-17224 split.

Why this module exists
----------------------
Before OMN-17224 every Claude Code tool call backgrounded a Python process
that called ``HandlerEventEmitEffect.handle()``. That handler lazily imports
``omnibase_infra.event_bus`` inside ``_build_default_adapter()``, which drags
in ``omnibase_infra.models`` -> ``rrh`` -> ``nodes`` -> ``dispatch`` and
builds ~2,497 Pydantic model classes. Profiled cost: **31.08s of a 31.65s
handle(), of which the actual Kafka publish was ~0.8s.**

At the operator's tool-call rate (peak 2,407/hr) that produced 14 concurrent
emitter processes burning ~270% CPU -- the emitters were themselves a major
cause of the load that then starved them.

The split
---------
* **This module (fast).** Serialize the event and append it to a local
  journal. Stdlib only. No network. Sub-100ms. Runs once per tool call.
* **The drainer (slow, singleton).** ``hook_emit_drainer.py`` pays the ~30s
  import **once**, holds one Kafka connection, and publishes the backlog.

``ONEX_HOOK_EMIT_MAX_IMPORT_DEPTH``-style cleverness is deliberately absent:
the only robust guarantee that this file stays cheap is that it imports
nothing outside the standard library. ``test_append_imports_nothing_heavy``
enforces that mechanically -- do not add a convenience import here, however
small it looks. That is exactly how the original cost got in.

Relationship to the two pre-existing "spools" (read before adding a third)
--------------------------------------------------------------------------
OMN-17050 documents that two unrelated directories are already both called
"the spool":

1. ``$ONEX_STATE_DIR/emit_spool`` -- written by ``receipt_mode.py``, read by
   nothing in the live path (79 stale records as of 2026-08-30).
2. ``$XDG_RUNTIME_DIR/onex/event-emit-effect-spool``, else
   ``/tmp/onex-event-emit-effect-spool`` -- ``node_event_emit_effect``'s own
   post-resolution spool, which its drain *does* read. ``XDG_RUNTIME_DIR`` is
   unset on this Mac, so it lives in ``/tmp``.

This journal is a **third directory, and deliberately so** -- it holds
*pre-resolution* events (an event type plus a raw payload, exactly as the
hook saw them), whereas (2) holds *post-resolution* per-topic records that
have already been through topic fan-out, enrichment and partition-key
derivation. Those are different stages, and collapsing them would mean
duplicating the handler's fan-out logic in this stdlib-only file -- which is
precisely the heavy code this module exists to avoid importing.

It is placed under ``ONEX_STATE_DIR`` (durable) rather than ``/tmp``. Fixing
(2)'s ``/tmp`` durability defect and triaging (1)'s stale records remain
OMN-17050's job; this module does not touch either.

Delivery semantics: **at-least-once**. A record is unlinked only after a
confirmed publish, so a drainer killed mid-publish replays rather than drops
(AC5). Duplicates are acceptable on a telemetry stream; loss is not.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "AppendOutcome",
    "JournalEntry",
    "JournalRecord",
    "SingletonLock",
    "ack",
    "append",
    "default_journal_dir",
    "default_lock_path",
    "list_pending",
]

# Bound chosen so a fully-stalled drainer holds roughly a day of the observed
# peak rate (2,407 events/hr) without unbounded disk growth. On overflow the
# OLDEST records are dropped and counted -- newest-wins, because for live
# operator telemetry a recent event is worth more than a stale one.
DEFAULT_MAX_RECORDS = 50_000

_SEQ_WIDTH = 20
_last_seq = 0


def default_journal_dir() -> Path:
    """Resolve the journal directory.

    ``ONEX_HOOK_EMIT_JOURNAL_DIR`` overrides. Otherwise it lands under
    ``ONEX_STATE_DIR`` -- durable, unlike the ``/tmp`` fallback OMN-17050
    describes for the emit node's own spool.
    """
    override = os.environ.get("ONEX_HOOK_EMIT_JOURNAL_DIR")
    if override:
        return Path(override)
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if state_dir:
        return Path(state_dir) / "hook_emit_journal"
    return Path.home() / ".onex_state" / "hook_emit_journal"


def default_lock_path() -> Path:
    """Singleton lock for the drainer, kept beside the journal it guards."""
    return default_journal_dir().parent / "hook_emit_drainer.lock"


@dataclass(frozen=True)
class JournalRecord:
    """One pre-resolution hook event, exactly as the hook observed it."""

    event_id: str
    event_type: str
    payload: dict[str, object]
    correlation_id: str | None
    queued_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "payload": self.payload,
                "correlation_id": self.correlation_id,
                "queued_at": self.queued_at.isoformat(),
            },
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> JournalRecord:
        data = json.loads(raw)
        queued_at = datetime.fromisoformat(data["queued_at"])
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=UTC)
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            payload=data["payload"],
            correlation_id=data.get("correlation_id"),
            queued_at=queued_at,
        )


@dataclass(frozen=True)
class JournalEntry:
    """A pending record together with the path it came from."""

    record: JournalRecord
    path: Path


@dataclass(frozen=True)
class AppendOutcome:
    """Result of one append.

    ``path`` is ``None`` when the event could not be written at all (an
    unserializable payload, or a filesystem that refused). ``dropped_count``
    reports how many older records this append evicted to stay under the
    bound -- surfaced rather than silent, so backpressure is observable.
    """

    path: Path | None
    dropped_count: int


def _next_seq() -> int:
    """Nanosecond monotonic sequence; filenames sort lexically for FIFO.

    Wall-clock nanoseconds survive process restarts, so a fresh hook process
    never sorts its event ahead of an existing backlog. The uuid suffix keeps
    filenames unique on a same-nanosecond collision.
    """
    global _last_seq
    seq = time.time_ns()
    if seq <= _last_seq:
        seq = _last_seq + 1
    _last_seq = seq
    return seq


def append(
    journal_dir: Path | str,
    *,
    event_type: str,
    payload: dict[str, object],
    correlation_id: str | None,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> AppendOutcome:
    """Append one event to the journal. Fast, bounded, and never raises.

    Fail-open is a hard requirement: this runs on the hook path of every
    tool call, so a bad payload or a full disk must degrade to "no event",
    never to a broken or slowed session.
    """
    journal_dir = Path(journal_dir)
    try:
        record = JournalRecord(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            payload=payload,
            correlation_id=correlation_id,
            queued_at=datetime.now(UTC),
        )
        blob = record.to_json()
    except (TypeError, ValueError):
        # Unserializable payload. Nothing to write; the session continues.
        return AppendOutcome(path=None, dropped_count=0)

    try:
        journal_dir.mkdir(parents=True, exist_ok=True)
        name = f"{_next_seq():0{_SEQ_WIDTH}d}_{record.event_id}.json"
        target = journal_dir / name
        # Write to a temp file then rename: a reader never observes a
        # partially-written record.
        tmp = journal_dir / f".{name}.tmp"
        tmp.write_text(blob)
        tmp.replace(target)
    except OSError:
        return AppendOutcome(path=None, dropped_count=0)

    dropped = _enforce_bound(journal_dir, max_records)
    return AppendOutcome(path=target, dropped_count=dropped)


def _enforce_bound(journal_dir: Path, max_records: int) -> int:
    """Drop oldest records beyond ``max_records``. Returns the drop count.

    Serialized under an exclusive lock so concurrent hook processes cannot
    race into a double-eviction. The lock is held only for the eviction
    branch -- the common case (under the bound) takes it briefly and does
    nothing, which is why the fast path stays fast.
    """
    if max_records < 1:
        return 0
    try:
        names = sorted(
            e.name
            for e in os.scandir(journal_dir)
            if e.is_file() and e.name.endswith(".json")
        )
    except OSError:
        return 0
    if len(names) <= max_records:
        return 0

    dropped = 0
    lock_path = journal_dir / ".bound.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return 0
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        # Re-list under the lock: another process may have already evicted.
        names = sorted(
            e.name
            for e in os.scandir(journal_dir)
            if e.is_file() and e.name.endswith(".json")
        )
        excess = len(names) - max_records
        for name in names[:excess]:
            try:
                (journal_dir / name).unlink()
                dropped += 1
            except OSError:
                pass
    except OSError:
        pass
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
    return dropped


def list_pending(journal_dir: Path | str) -> list[JournalEntry]:
    """Return pending records in FIFO order. Corrupt files are skipped.

    A single unreadable record must never stall the whole drain, so parse
    failures are dropped from the result rather than raised.
    """
    journal_dir = Path(journal_dir)
    try:
        names = sorted(
            e.name
            for e in os.scandir(journal_dir)
            if e.is_file() and e.name.endswith(".json")
        )
    except OSError:
        return []

    entries: list[JournalEntry] = []
    for name in names:
        path = journal_dir / name
        try:
            entries.append(
                JournalEntry(
                    record=JournalRecord.from_json(path.read_text()), path=path
                )
            )
        except (OSError, ValueError, KeyError):
            continue
    return entries


def ack(entry: JournalEntry) -> None:
    """Remove a successfully-published record. Idempotent."""
    try:
        entry.path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


class SingletonLock:
    """Advisory whole-file lock admitting exactly one live drainer.

    Uses ``fcntl.flock`` rather than a pidfile: the kernel releases the lock
    when the holder dies, so a killed or crashed drainer cannot wedge the
    system permanently (AC5). A pidfile would need stale-pid reaping and
    would race.

    macOS ships no ``flock(1)`` utility (memory
    ``reference_macos_no_flock_use_fcntl_shim``), but ``fcntl.flock`` is a
    real syscall wrapper on Darwin and is the right primitive here.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to take the lock. Returns False if another holder has it."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self._path), os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                return False
            return False
        try:
            os.ftruncate(fd, 0)
            os.write(fd, f"{os.getpid()}\n".encode())
        except OSError:
            pass
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = None

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()
