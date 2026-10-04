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
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "DEFAULT_LOCK_WAIT_S",
    "LOSS_LOG_ENV",
    "LOSS_LOG_FILENAME",
    "AppendOutcome",
    "JournalEntry",
    "JournalLockTimeout",
    "JournalRecord",
    "JournalWriteError",
    "SingletonLock",
    "ack",
    "append",
    "default_journal_dir",
    "default_lock_path",
    "enforce_bound",
    "list_pending",
    "loss_log_path",
    "record_loss",
]

# OMN-20535 AC2: every journal record the drainer does not publish -- evicted over
# the bound, acked as unpublishable, or moved to the dead-letter -- is one line of
# this file beside the journal directory, carrying the work-ledger ``row_id`` when
# the record is a ``work.ledger.*`` event. The work-ledger parity check reads it to
# classify a row missing from the database as lost in the journal rather than
# unexplained. ``ONEX_HOOK_EMIT_LOSS_LOG`` overrides the path.
LOSS_LOG_FILENAME = "hook_emit_journal_losses.jsonl"
LOSS_LOG_ENV = "ONEX_HOOK_EMIT_LOSS_LOG"
_LEDGER_EVENT_PREFIX = "work.ledger."

# Bound chosen so a fully-stalled drainer holds roughly a day of the observed
# peak rate (2,407 events/hr) without unbounded disk growth. On overflow the
# OLDEST records are dropped and counted -- newest-wins, because for live
# operator telemetry a recent event is worth more than a stale one.
DEFAULT_MAX_RECORDS = 50_000

_SEQ_WIDTH = 20

# OMN-20110: the bounded runner hands a writer a pipe it reports progress on.
# A record renamed into the journal is durable whatever the process does next,
# so the runner must not call the emit "NOT recorded" when it was.
ACK_FD_ENV = "ONEX_HOOK_EMIT_ACK_FD"
ACK_JOURNALLED = b"j"
ACK_DONE = b"d"


def signal_ack(kind: bytes) -> None:
    """Tell the bounded runner, if there is one, that a record is journalled
    (``ACK_JOURNALLED``) or that the emit is complete (``ACK_DONE``).

    A no-op outside the runner. Never raises: a progress report must not turn
    a good write into a failure.
    """
    raw = os.environ.get(ACK_FD_ENV)
    if not raw or not raw.isdigit():
        return
    try:
        os.write(int(raw), kind)
    except OSError:
        pass


def emit_done() -> None:
    """The writer is finished: the runner may return without waiting for exit."""
    signal_ack(ACK_DONE)


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


class JournalWriteError(OSError):
    """An append could not be written. Raised, never swallowed (OMN-20110).

    The hook path runs every append under ``hook_emit_bounded``, which turns
    this into a blocking error that names the cause and an operator alarm.
    Returning "no event" here is how emits failed silently before.
    """


class JournalLockTimeout(TimeoutError):
    """The bound lock was not acquired inside its wait budget (OMN-20110)."""


@dataclass(frozen=True)
class AppendOutcome:
    """Result of one append: the path of the record written."""

    path: Path


# Seconds a bound enforcer waits for the eviction lock before giving up with
# JournalLockTimeout. A blocking flock with no deadline is one of the two ways
# an emit could wait forever.
DEFAULT_LOCK_WAIT_S = 2.0


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
) -> AppendOutcome:
    """Append one event to the journal: one temp write and one rename.

    O(1) in the size of the backlog, by construction (OMN-20110). Before this
    ticket every append scanned the whole journal directory to enforce the
    bound; with a 29,839-record backlog on 2026-09-29 that scan took minutes
    under the directory lock, thousands of hook processes queued behind it in
    uninterruptible wait, and the operator Mac ran out of processes. The bound
    is now the drainer's job (:func:`enforce_bound`), done once per cycle by
    one process.

    Raises :class:`JournalWriteError` when the record cannot be written.
    """
    journal_dir = Path(journal_dir)
    record = JournalRecord(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
        queued_at=datetime.now(UTC),
    )
    blob = record.to_json()

    name = f"{_next_seq():0{_SEQ_WIDTH}d}_{record.event_id}.json"
    target = journal_dir / name
    # Write to a temp file then rename: a reader never observes a
    # partially-written record.
    tmp = journal_dir / f".{name}.tmp"
    try:
        journal_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(blob)
        tmp.replace(target)
    except OSError as exc:
        raise JournalWriteError(
            exc.errno, f"cannot write journal record in {journal_dir}: {exc.strerror}"
        ) from exc
    signal_ack(ACK_JOURNALLED)
    return AppendOutcome(path=target)


def loss_log_path(journal_dir: Path | str) -> Path:
    """Where the loss lines go: the override, else beside the journal directory."""
    override = os.environ.get(LOSS_LOG_ENV)
    if override:
        return Path(override)
    return Path(journal_dir).parent / LOSS_LOG_FILENAME


def record_loss(
    journal_dir: Path | str,
    *,
    disposition: str,
    record: JournalRecord | None,
    journal_file: str,
    detail: str = "",
) -> bool:
    """Append one loss line. Returns False when it could not be written; never raises.

    ``record`` is None when the evicted file could not be read; the line still
    names the file, so the loss is counted even when its row id is unknown.
    """
    row_id: object = None
    if record is not None and record.event_type.startswith(_LEDGER_EVENT_PREFIX):
        candidate = record.payload.get("row_id")
        row_id = candidate if isinstance(candidate, str) and candidate else None
    line = {
        "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host": socket.gethostname().split(".")[0],
        "disposition": disposition,
        "journal_file": journal_file,
        "event_id": None if record is None else record.event_id,
        "event_type": None if record is None else record.event_type,
        "correlation_id": None if record is None else record.correlation_id,
        "row_id": row_id,
        "detail": detail,
    }
    path = loss_log_path(journal_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        return False
    return True


def _record_eviction(journal_dir: Path, name: str) -> None:
    try:
        record: JournalRecord | None = JournalRecord.from_json(
            (journal_dir / name).read_text()
        )
        detail = "evicted oldest-first over the journal bound"
    except (OSError, ValueError, KeyError) as exc:
        record = None
        detail = f"evicted over the journal bound; record unreadable: {exc}"
    record_loss(
        journal_dir,
        disposition="dropped-over-bound",
        record=record,
        journal_file=name,
        detail=detail,
    )


def _sorted_record_names(journal_dir: Path) -> list[str]:
    return sorted(
        e.name
        for e in os.scandir(journal_dir)
        if e.is_file() and e.name.endswith(".json")
    )


def _acquire_bounded(fd: int, wait_s: float) -> None:
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if exc.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                raise
        if time.monotonic() >= deadline:
            raise JournalLockTimeout(f"journal bound lock busy for {wait_s:g}s")
        time.sleep(0.02)


def enforce_bound(
    journal_dir: Path | str,
    max_records: int = DEFAULT_MAX_RECORDS,
    *,
    lock_wait_s: float = DEFAULT_LOCK_WAIT_S,
) -> int:
    """Drop the oldest records beyond ``max_records``. Returns the drop count.

    Each dropped record is first written to the loss log (:func:`record_loss`),
    so a dropped work-ledger row is traceable by its row id (OMN-20535).

    Called by the drainer once per cycle, never on the hook path. Serialized
    under an exclusive lock whose wait is bounded by ``lock_wait_s``; a lock
    that stays busy raises :class:`JournalLockTimeout` rather than waiting.
    """
    journal_dir = Path(journal_dir)
    if max_records < 1:
        return 0
    try:
        names = _sorted_record_names(journal_dir)
    except FileNotFoundError:
        return 0
    if len(names) <= max_records:
        return 0

    dropped = 0
    fd = os.open(str(journal_dir / ".bound.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _acquire_bounded(fd, lock_wait_s)
        # Re-list under the lock: another enforcer may have already evicted.
        names = _sorted_record_names(journal_dir)
        excess = len(names) - max_records
        for name in names[: max(excess, 0)]:
            _record_eviction(journal_dir, name)
            try:
                (journal_dir / name).unlink()
                dropped += 1
            except FileNotFoundError:
                pass
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
    return dropped


def list_pending(
    journal_dir: Path | str, *, limit: int | None = None
) -> list[JournalEntry]:
    """Return up to ``limit`` pending records in FIFO order.

    Only the records returned are read and parsed. Before OMN-20110 the
    drainer parsed the whole journal to publish a 200-record batch, so a
    backlog made every cycle slower, which grew the backlog. Corrupt files
    are skipped: a single unreadable record must never stall the drain.
    """
    journal_dir = Path(journal_dir)
    try:
        names = _sorted_record_names(journal_dir)
    except FileNotFoundError:
        return []

    entries: list[JournalEntry] = []
    for name in names:
        if limit is not None and len(entries) >= limit:
            break
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
