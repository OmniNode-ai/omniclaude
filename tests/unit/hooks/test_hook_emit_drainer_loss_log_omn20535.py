# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The drainer records the row_id of every work-ledger record it loses (OMN-20535 AC2).

The work-ledger parity check (omnimarket ``node_projection_work_ledger.parity``)
finds rows that are in the markdown ledger and not in the database. To say WHY a
row is missing it needs a record, keyed by the row's ``row_id``, of each journal
record the drainer did not publish: evicted over the journal bound, acked as
unpublishable, or moved to the dead-letter. Before this ticket the first two left
a log line with no row id and the third left a reason file with no row id, so a
row lost on any of the three paths read as unexplained.

Each loss is one line of ``hook_emit_journal_losses.jsonl`` beside the journal
directory. ``row_id`` is the payload's ``row_id`` for a ``work.ledger.*`` record
and null for any other event type.
"""

from __future__ import annotations

import json
from pathlib import Path

import hook_emit_drainer as drainer
import hook_emit_journal as journal
import pytest

# tests/conftest.py puts plugins/onex/hooks/lib on sys.path for these imports.
pytestmark = pytest.mark.unit

ROW_A = "a" * 64
ROW_B = "b" * 64


@pytest.fixture
def jdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(journal.LOSS_LOG_ENV, raising=False)
    d = tmp_path / "journal"
    d.mkdir()
    return d


def _ledger(jdir: Path, row_id: str, row_type: str = "status") -> None:
    journal.append(
        jdir,
        event_type=f"work.ledger.{row_type}",
        payload={"ledger_id": "rolling-work-ledger", "row_id": row_id, "raw_row": "x"},
        correlation_id=row_id,
    )


def _losses(jdir: Path) -> list[dict[str, object]]:
    path = journal.loss_log_path(jdir)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class RefusingEmitter:
    """Refuses one event class; publishes everything else."""

    def __init__(self, refused: str) -> None:
        self.refused = refused
        self.published: list[str] = []

    def publish(self, record: journal.JournalRecord) -> bool:
        if record.event_type == self.refused:
            return False
        self.published.append(record.event_id)
        return True


def test_drainer_dead_letter_row_id_recorded_on_quarantine(jdir: Path) -> None:
    _ledger(jdir, ROW_A, "claim")
    journal.append(jdir, event_type="ok.class", payload={}, correlation_id=None)
    counts: dict[str, int] = {}
    refused: dict[str, str] = {}
    for _ in range(drainer.DEFAULT_QUARANTINE_AFTER_FAILURES + 1):
        drainer.drain_once(
            jdir,
            RefusingEmitter("work.ledger.claim"),
            failure_counts=counts,
            refused_event_types=refused,
        )

    losses = _losses(jdir)
    assert [(x["disposition"], x["row_id"]) for x in losses] == [
        ("dead-lettered", ROW_A)
    ]
    entry = losses[0]
    assert entry["event_type"] == "work.ledger.claim"
    assert entry["ts"] and entry["host"]
    assert (jdir / "quarantine" / str(entry["journal_file"])).exists(), (
        "the loss line must name the dead-lettered file, so the record can be found and replayed"
    )


def test_drainer_dead_letter_row_id_recorded_on_bound_eviction(jdir: Path) -> None:
    _ledger(jdir, ROW_A)
    _ledger(jdir, ROW_B)
    for i in range(3):
        journal.append(
            jdir, event_type="tool.executed", payload={"i": i}, correlation_id=None
        )

    assert journal.enforce_bound(jdir, 3) == 2

    losses = _losses(jdir)
    assert [(x["disposition"], x["row_id"]) for x in losses] == [
        ("dropped-over-bound", ROW_A),
        ("dropped-over-bound", ROW_B),
    ]


def test_drainer_dead_letter_row_id_null_for_non_ledger_records(jdir: Path) -> None:
    for i in range(3):
        journal.append(
            jdir,
            event_type="tool.executed",
            payload={"row_id": "z"},
            correlation_id=None,
        )

    assert journal.enforce_bound(jdir, 1) == 2

    losses = _losses(jdir)
    assert len(losses) == 2
    assert {x["row_id"] for x in losses} == {None}, (
        "only a work.ledger record carries a ledger row id; another event's payload key is not one"
    )


def test_drainer_dead_letter_row_id_recorded_for_an_unreadable_evicted_record(
    jdir: Path,
) -> None:
    (jdir / "00000000000000000001_corrupt.json").write_text("{not json")
    journal.append(jdir, event_type="tool.executed", payload={}, correlation_id=None)

    assert journal.enforce_bound(jdir, 1) == 1

    losses = _losses(jdir)
    assert [(x["disposition"], x["journal_file"], x["row_id"]) for x in losses] == [
        ("dropped-over-bound", "00000000000000000001_corrupt.json", None)
    ]
    assert "unreadable" in str(losses[0]["detail"])


def test_drainer_dead_letter_row_id_recorded_on_unpublishable_ack(jdir: Path) -> None:
    _ledger(jdir, ROW_A, "terminal")
    entry = journal.list_pending(jdir)[0]

    def explode(**_kwargs: object) -> object:
        raise ValueError("bad request")

    emitter = drainer._Emitter(
        on_unpublishable=lambda record, why: journal.record_loss(
            jdir,
            disposition="dropped-unpublishable",
            record=record,
            journal_file=entry.path.name,
            detail=why,
        )
    )
    emitter._handler = object()
    emitter._request_cls = explode

    assert emitter.publish(entry.record) is True, (
        "an unpublishable record is still acked"
    )
    losses = _losses(jdir)
    assert [(x["disposition"], x["row_id"]) for x in losses] == [
        ("dropped-unpublishable", ROW_A)
    ]
    assert "bad request" in str(losses[0]["detail"])


def test_drainer_dead_letter_row_id_log_path_override(
    jdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "elsewhere" / "losses.jsonl"
    monkeypatch.setenv(journal.LOSS_LOG_ENV, str(target))
    assert journal.loss_log_path(jdir) == target
    monkeypatch.delenv(journal.LOSS_LOG_ENV)
    assert journal.loss_log_path(jdir) == jdir.parent / journal.LOSS_LOG_FILENAME
