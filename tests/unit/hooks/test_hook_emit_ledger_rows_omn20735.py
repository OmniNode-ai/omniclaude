# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Work-ledger rows survive the journal bound and an empty drainer status (OMN-20735).

53 lanes lost 225 ledger rows because they share the hook-emit journal with
high-volume hook events. Two loss classes:

* ``enforce_bound`` evicts the OLDEST records over the bound, and a ledger row
  is old by the time a stalled drainer is noticed. A ``work.ledger.*`` record is
  now exempt: the bound evicts only other event types.
* The dual write refused to journal a row when the drainer status listed no
  publishable types. A row is now DEFERRED to ``deferred/`` beside the journal and
  released into the journal by the drainer once its status lists the type.
"""

from __future__ import annotations

import json
from pathlib import Path

import hook_emit_append as appender
import hook_emit_drainer as drainer
import hook_emit_health as health
import hook_emit_journal as journal
import pytest

# tests/conftest.py puts plugins/onex/hooks/lib on sys.path for these imports.
pytestmark = pytest.mark.unit

ROW_A = "a" * 64
ROW_B = "b" * 64
LEDGER_TYPE = "work.ledger.typed.claim"


@pytest.fixture
def jdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(journal.LOSS_LOG_ENV, raising=False)
    d = tmp_path / "journal"
    d.mkdir()
    return d


def _ledger(jdir: Path, row_id: str, event_type: str = LEDGER_TYPE) -> None:
    journal.append(
        jdir,
        event_type=event_type,
        payload={"ledger_id": "rolling-work-ledger", "row_id": row_id, "raw_row": "x"},
        correlation_id=row_id,
    )


def _hook(jdir: Path, count: int) -> None:
    for i in range(count):
        journal.append(
            jdir, event_type="tool.executed", payload={"i": i}, correlation_id=None
        )


def _pending_types(jdir: Path) -> list[str]:
    return [e.record.event_type for e in journal.list_pending(jdir)]


def _losses(jdir: Path) -> list[dict[str, object]]:
    path = journal.loss_log_path(jdir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_status(path: Path, types: tuple[str, ...] | None) -> None:
    health.write_status(
        path,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=types,
        ),
    )


class AcceptingEmitter:
    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, record: journal.JournalRecord) -> bool:
        self.published.append(record.event_type)
        return True


# ---------------------------------------------------------------------------
# AC1: ledger_record_never_dropped_over_bound
# ---------------------------------------------------------------------------


def test_ledger_record_never_dropped_over_bound_oldest_first(jdir: Path) -> None:
    """The ledger rows are the OLDEST records; the bound still spares them."""
    _ledger(jdir, ROW_A)
    _ledger(jdir, ROW_B, "work.ledger.typed.terminal")
    _hook(jdir, 6)

    dropped = journal.enforce_bound(jdir, 4)

    assert dropped == 4
    types = _pending_types(jdir)
    assert types.count(LEDGER_TYPE) == 1
    assert types.count("work.ledger.typed.terminal") == 1
    assert types.count("tool.executed") == 2
    assert {x["event_type"] for x in _losses(jdir)} == {"tool.executed"}


def test_ledger_record_never_dropped_over_bound_when_journal_is_all_ledger(
    jdir: Path,
) -> None:
    for n in range(5):
        _ledger(jdir, f"{n:064d}")

    assert journal.enforce_bound(jdir, 2) == 0

    assert len(journal.list_pending(jdir)) == 5
    assert _losses(jdir) == []


def test_ledger_record_never_dropped_over_bound_prefix_covers_every_ledger_type(
    jdir: Path,
) -> None:
    _ledger(jdir, ROW_A, "work.ledger.status")
    _ledger(jdir, ROW_B, "work.ledger.typed.msg")
    _hook(jdir, 3)

    assert journal.enforce_bound(jdir, 1) == 3

    assert sorted(_pending_types(jdir)) == [
        "work.ledger.status",
        "work.ledger.typed.msg",
    ]


def test_ledger_record_never_dropped_over_bound_positive_control(jdir: Path) -> None:
    """Non-ledger records are still evicted oldest-first, so the bound still holds."""
    _hook(jdir, 5)

    assert journal.enforce_bound(jdir, 2) == 3

    assert len(journal.list_pending(jdir)) == 2


def test_ledger_record_never_dropped_over_bound_unreadable_still_evicted(
    jdir: Path,
) -> None:
    (jdir / "00000000000000000001_corrupt.json").write_text("{not json")
    _ledger(jdir, ROW_A)
    _hook(jdir, 1)

    assert journal.enforce_bound(jdir, 2) == 1

    assert not (jdir / "00000000000000000001_corrupt.json").exists()
    assert _pending_types(jdir) == [LEDGER_TYPE, "tool.executed"]


# ---------------------------------------------------------------------------
# AC2: drainer_gate_defers_ledger_rows
# ---------------------------------------------------------------------------


def _append(jdir: Path, status: Path, event_type: str = LEDGER_TYPE) -> int:
    return appender.main(
        [
            "--event-type",
            event_type,
            "--payload",
            json.dumps({"row_id": ROW_A, "raw_row": "x"}),
            "--correlation-id",
            ROW_A,
            "--journal-dir",
            str(jdir),
            "--drainer-status",
            str(status),
        ]
    )


def _deferred(jdir: Path) -> list[Path]:
    d = jdir / journal.DEFERRED_DIRNAME
    return sorted(d.glob("*.json")) if d.exists() else []


def test_drainer_gate_defers_ledger_rows_when_status_lists_no_types(
    jdir: Path, tmp_path: Path
) -> None:
    status = tmp_path / "status.json"
    _write_status(status, None)

    assert _append(jdir, status) == 0

    assert journal.list_pending(jdir) == [], "the head of the journal is not touched"
    assert len(_deferred(jdir)) == 1, "the row is deferred, not skipped"


def test_drainer_gate_defers_ledger_rows_when_status_file_is_absent(
    jdir: Path, tmp_path: Path
) -> None:
    assert _append(jdir, tmp_path / "missing.json") == 0

    assert journal.list_pending(jdir) == []
    assert len(_deferred(jdir)) == 1


def test_drainer_gate_defers_ledger_rows_when_type_is_not_listed(
    jdir: Path, tmp_path: Path
) -> None:
    status = tmp_path / "status.json"
    _write_status(status, ("tool.executed",))

    assert _append(jdir, status) == 0

    assert journal.list_pending(jdir) == []
    assert len(_deferred(jdir)) == 1


def test_drainer_gate_defers_ledger_rows_publishable_row_is_journalled_directly(
    jdir: Path, tmp_path: Path
) -> None:
    status = tmp_path / "status.json"
    _write_status(status, (LEDGER_TYPE,))

    assert _append(jdir, status) == 0

    assert _pending_types(jdir) == [LEDGER_TYPE]
    assert _deferred(jdir) == []


def test_drainer_gate_defers_ledger_rows_other_events_are_not_gated(
    jdir: Path, tmp_path: Path
) -> None:
    status = tmp_path / "status.json"
    _write_status(status, None)

    assert _append(jdir, status, "tool.executed") == 0

    assert _pending_types(jdir) == ["tool.executed"]
    assert _deferred(jdir) == []


def test_drainer_gate_defers_ledger_rows_released_once_type_is_listed(
    jdir: Path,
) -> None:
    journal.defer(
        jdir,
        event_type=LEDGER_TYPE,
        payload={"row_id": ROW_A},
        correlation_id=ROW_A,
    )

    assert journal.release_deferred(jdir, None) == 0
    assert journal.release_deferred(jdir, ("tool.executed",)) == 0
    assert journal.list_pending(jdir) == []

    assert journal.release_deferred(jdir, (LEDGER_TYPE,)) == 1

    assert _pending_types(jdir) == [LEDGER_TYPE]
    assert _deferred(jdir) == []
    assert _losses(jdir) == []


def test_drainer_gate_defers_ledger_rows_drain_once_publishes_released_row(
    jdir: Path,
) -> None:
    journal.defer(
        jdir,
        event_type=LEDGER_TYPE,
        payload={"row_id": ROW_A},
        correlation_id=ROW_A,
    )
    emitter = AcceptingEmitter()

    drainer.drain_once(jdir, emitter, publishable=("tool.executed",))
    assert emitter.published == []
    assert len(_deferred(jdir)) == 1

    published, failed, dead = drainer.drain_once(
        jdir, emitter, publishable=(LEDGER_TYPE,)
    )

    assert (published, failed, dead) == (1, 0, 0)
    assert emitter.published == [LEDGER_TYPE]
    assert _deferred(jdir) == []


def test_drainer_gate_defers_ledger_rows_deferred_rows_do_not_count_toward_the_bound(
    jdir: Path,
) -> None:
    for n in range(4):
        journal.defer(
            jdir,
            event_type=LEDGER_TYPE,
            payload={"row_id": f"{n:064d}"},
            correlation_id=None,
        )
    _hook(jdir, 2)

    assert journal.enforce_bound(jdir, 2) == 0
    assert len(_deferred(jdir)) == 4
