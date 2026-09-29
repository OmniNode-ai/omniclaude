# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20110 AC1/AC2: the journal append is O(1) and the drainer lists one batch.

On 2026-09-29 every hook append scanned the whole journal directory to
enforce the bound. With a 29,839-record backlog, thousands of hook processes
sat in ``__getdirentries64`` behind the directory lock and the operator Mac
ran out of processes. These tests pin the two costs that made it possible.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_emit_journal as journal  # noqa: E402


def test_append_does_not_scan_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jdir = tmp_path / "journal"
    for i in range(50):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)

    scans: list[object] = []
    real_scandir = os.scandir

    def counting_scandir(path: object) -> object:
        scans.append(path)
        return real_scandir(path)  # type: ignore[arg-type]

    monkeypatch.setattr(journal.os, "scandir", counting_scandir)
    journal.append(jdir, event_type="e", payload={"i": 50}, correlation_id=None)
    assert scans == [], "append must not list the journal directory"


def test_append_does_not_scan_even_over_the_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound belongs to the drainer; an append over it still writes one file."""
    jdir = tmp_path / "journal"
    for i in range(20):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)
    monkeypatch.setattr(journal, "DEFAULT_MAX_RECORDS", 5)
    monkeypatch.setattr(
        journal.os, "scandir", lambda *_a: pytest.fail("append scanned the journal")
    )
    journal.append(jdir, event_type="e", payload={"i": 99}, correlation_id=None)


def test_append_write_failure_raises(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    with pytest.raises(journal.JournalWriteError):
        journal.append(blocker / "j", event_type="e", payload={}, correlation_id=None)


def test_list_pending_limit_parses_only_one_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    jdir = tmp_path / "journal"
    for i in range(40):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)

    parsed: list[str] = []
    real = journal.JournalRecord.from_json

    def counting(blob: str) -> journal.JournalRecord:
        parsed.append(blob)
        return real(blob)

    monkeypatch.setattr(journal.JournalRecord, "from_json", staticmethod(counting))
    batch = journal.list_pending(jdir, limit=7)
    assert [e.record.payload["i"] for e in batch] == list(range(7))
    assert len(parsed) == 7, "only the batch may be read and parsed"


def test_enforce_bound_drops_oldest_and_counts(tmp_path: Path) -> None:
    jdir = tmp_path / "journal"
    for i in range(12):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)
    assert journal.enforce_bound(jdir, 5) == 7
    assert [e.record.payload["i"] for e in journal.list_pending(jdir)] == list(
        range(7, 12)
    )


def test_enforce_bound_lock_wait_is_bounded(tmp_path: Path) -> None:
    import fcntl
    import time

    jdir = tmp_path / "journal"
    for i in range(4):
        journal.append(jdir, event_type="e", payload={"i": i}, correlation_id=None)
    fd = os.open(str(jdir / ".bound.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    # flock locks are per open file description: a second description in this
    # same process contends exactly like another process would.
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        t0 = time.monotonic()
        with pytest.raises(journal.JournalLockTimeout, match="busy"):
            journal.enforce_bound(jdir, 1, lock_wait_s=0.3)
        assert time.monotonic() - t0 < 2.0
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
