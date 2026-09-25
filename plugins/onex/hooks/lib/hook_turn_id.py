# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Mint a turn id for a Claude Code session turn (OMN-19517).

WHY THIS EXISTS. Claude Code's hook input carries no turn identifier, so the
appender used to journal ``turn_id: null`` for every Claude record. The capture
redaction contract does not classify ``turn_id``, and its fail-closed default is
``capture_hashed``, so the emit handler replaced each null with
``sha256("null")``. Measured on the lab dev-lane broker at 2026-09-25T01:37:40Z: all
of the last 20,000 tool-executed records carried that one digest across 31
sessions, and 187 prompt-submitted sessions carried it too. A key that is the
same for every session cannot group a turn.

WHAT A TURN IS HERE. A ``prompt.submitted`` event opens turn ``n + 1`` for its
session. Every ``tool.executed`` event after it, including a subagent's (a
subagent shares its parent's session id), belongs to that turn until the next
prompt. The id is ``<session_id>:turn-<n>``, so it is unique across sessions by
construction and ordered within one. A tool call seen before any prompt (a
session that was already running when this hook was installed) is turn 0 of
its session. Session start and end are not turns, and stay null, which is what
``hooks/contracts/hook_actor_envelope.yaml`` declares for both actors.

A host-supplied turn id (Codex sends one) always wins and is never rewritten.

CONCURRENCY. The appender is forked and disowned per hook, so two allocations
for one session can overlap. The counter file is read and rewritten under an
exclusive ``fcntl.flock`` on the file itself, so two prompts never allocate the
same turn. A prompt's append runs while the model is still answering, so it
lands before the first tool call of its turn in practice; this module does not
try to order two different processes beyond that.

Stdlib only, like every module on the hook fast path: see
``hook_emit_journal`` for why that constraint is load-bearing.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import time
from pathlib import Path
from typing import IO

#: The directory, beside the journal, that holds one counter file per session.
TURN_DIRNAME = "hook_turns"

#: Counter files untouched for this long are removed when a session starts.
#: A session resumed after that loses nothing but turn continuity: its next
#: prompt restarts at turn 1 with the same session id, which keeps the id
#: unique only if no record from the old turns is still in flight, and after
#: thirty days none is.
STALE_AFTER_SECONDS = 30 * 24 * 3600

_OPENS_A_TURN = frozenset({"prompt.submitted"})
_INSIDE_A_TURN = frozenset({"tool.executed"})
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def turn_dir_for(journal_dir: Path) -> Path:
    """The counter directory for a journal: a sibling, under the same state dir."""
    return journal_dir.parent / TURN_DIRNAME


def _counter_path(turn_dir: Path, session_id: str) -> Path:
    name = session_id if _SAFE_NAME.match(session_id) else ""
    if not name or name in {".", ".."}:
        name = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return turn_dir / f"{name}.turn"


def _format(session_id: str, seq: int) -> str:
    return f"{session_id}:turn-{seq}"


def _read_seq(handle: IO[str]) -> int:
    handle.seek(0)
    raw = handle.read().strip()
    try:
        seq = int(raw)
    except ValueError:
        return 0
    return seq if seq >= 0 else 0


def _open_turn(turn_dir: Path, session_id: str) -> int:
    turn_dir.mkdir(parents=True, exist_ok=True)
    path = _counter_path(turn_dir, session_id)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            seq = _read_seq(handle) + 1
            handle.seek(0)
            handle.truncate()
            handle.write(f"{seq}\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return seq


def _current_turn(turn_dir: Path, session_id: str) -> int:
    path = _counter_path(turn_dir, session_id)
    try:
        with open(path, encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                return _read_seq(handle)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError:
        return 0


def prune_stale(turn_dir: Path, *, now: float | None = None) -> int:
    """Remove counter files not touched for ``STALE_AFTER_SECONDS``. Returns the count."""
    cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
    removed = 0
    try:
        candidates = list(turn_dir.glob("*.turn"))
    except OSError:
        return 0
    for path in candidates:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def resolve_turn_id(
    turn_dir: Path,
    *,
    event_type: str,
    session_id: str | None,
    host_turn_id: str | None,
) -> str | None:
    """The turn id to stamp on one record, or ``None`` when it is not a turn event."""
    host = (host_turn_id or "").strip()
    if host:
        return host
    session = (session_id or "").strip()
    if not session:
        return None
    if event_type in _OPENS_A_TURN:
        return _format(session, _open_turn(turn_dir, session))
    if event_type in _INSIDE_A_TURN:
        return _format(session, _current_turn(turn_dir, session))
    if event_type == "session.started":
        prune_stale(turn_dir)
    return None
