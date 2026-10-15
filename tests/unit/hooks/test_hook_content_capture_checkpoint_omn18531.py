# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The ``checkpoint`` capture kind (OMN-18531, plan task TA.20a).

The session checkpoint JSON ``omni.session-checkpoint/1`` is written by the
session-start checkpoint hook. ``hook_content_capture.py --kind checkpoint``
journals that written file, verbatim, through the same capture-redaction
contract and the same ``content.captured`` event as every other kind.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Any

import hook_content_capture as capture_mod
import hook_emit_health as health
import hook_emit_journal as journal
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

SESSION = "1a1a1a1a-2222-3333-4444-555555555555"
GITHUB_FAKE = "gh" + "p_" + "FAKE" + "a1b2" * 9

#: Deliberately not canonical JSON: the capture must keep the file's bytes, so
#: a re-serialisation (sorted keys, other spacing) would change the digest.
CHECKPOINT_TEXT = (
    '{\n  "schema": "omni.session-checkpoint/1",\n'
    '  "written_at": "2026-10-15T05:00:00Z",\n'
    '  "lanes": ["orchestrator-bb1a", "omn18531-ta20a"],\n'
    '  "note": "café — open work"\n}\n'
)


def _status(directory: Path, event_types: tuple[str, ...]) -> None:
    health.write_status(
        capture_mod.status_path_for(directory),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=event_types,
        ),
    )


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _status(directory, ("content.captured", "hook.event"))
    return directory


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "onex_home", lambda: tmp_path / "no-onex")


def _records(journal_dir: Path) -> list[dict[str, Any]]:
    records = [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == "content.captured"
    ]
    return sorted(records, key=lambda r: r["chunk_index"])


def _reassembled(records: list[dict[str, Any]]) -> str:
    return "".join(r["content"] for r in records)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_checkpoint_write_yields_one_row_matching_the_written_file(
    jdir: Path,
) -> None:
    written = capture_mod.capture(
        {"checkpoint": CHECKPOINT_TEXT},
        kind="checkpoint",
        journal_dir=jdir,
        session_id=SESSION,
    )

    assert written == 1
    records = _records(jdir)
    assert len(records) == 1
    record = records[0]
    assert record["content_kind"] == "checkpoint"
    assert record["hook_source"] == "checkpoint"
    assert record["session_id"] == SESSION
    assert _sha(_reassembled(records)) == _sha(CHECKPOINT_TEXT)
    assert record["content_sha256"] == _sha(CHECKPOINT_TEXT)


def test_main_journals_the_checkpoint_stdin_verbatim(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(CHECKPOINT_TEXT))

    rc = capture_mod.main(
        [
            "--kind",
            "checkpoint",
            "--session-id",
            SESSION,
            "--journal-dir",
            str(jdir),
        ]
    )

    assert rc == 0
    records = _records(jdir)
    assert len(records) == 1
    assert records[0]["content_kind"] == "checkpoint"
    assert records[0]["content"] == CHECKPOINT_TEXT
    assert _sha(records[0]["content"]) == _sha(CHECKPOINT_TEXT)


def test_a_checkpoint_larger_than_one_chunk_reassembles_to_the_file(
    jdir: Path,
) -> None:
    body = json.dumps(
        {
            "schema": "omni.session-checkpoint/1",
            "written_at": "2026-10-15T05:00:00Z",
            "notes": ["open work item " + "x" * 90] * 1500,
        },
        indent=2,
    )
    assert len(body) > 65536

    written = capture_mod.capture(
        {"checkpoint": body},
        kind="checkpoint",
        journal_dir=jdir,
        session_id=SESSION,
    )

    records = _records(jdir)
    assert written == len(records) > 1
    assert _sha(_reassembled(records)) == _sha(body)


def test_the_opt_out_switch_journals_no_checkpoint(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(capture_mod.OPT_OUT_ENV, "0")

    written = capture_mod.capture(
        {"checkpoint": CHECKPOINT_TEXT},
        kind="checkpoint",
        journal_dir=jdir,
        session_id=SESSION,
    )

    assert written == 0
    assert _records(jdir) == []


def test_a_drainer_that_cannot_publish_the_type_journals_no_checkpoint(
    jdir: Path,
) -> None:
    _status(jdir, ("hook.event",))

    written = capture_mod.capture(
        {"checkpoint": CHECKPOINT_TEXT},
        kind="checkpoint",
        journal_dir=jdir,
        session_id=SESSION,
    )

    assert written == 0
    assert _records(jdir) == []


def test_a_credential_in_the_checkpoint_never_crosses(jdir: Path) -> None:
    text = json.dumps({"schema": "omni.session-checkpoint/1", "t": GITHUB_FAKE})

    capture_mod.capture(
        {"checkpoint": text},
        kind="checkpoint",
        journal_dir=jdir,
        session_id=SESSION,
    )

    records = _records(jdir)
    assert records
    assert GITHUB_FAKE not in json.dumps(records)
    assert any(r["producer_redaction"] for r in records)


def test_an_empty_checkpoint_journals_nothing(jdir: Path) -> None:
    assert (
        capture_mod.capture(
            {"checkpoint": ""},
            kind="checkpoint",
            journal_dir=jdir,
            session_id=SESSION,
        )
        == 0
    )
    assert _records(jdir) == []
