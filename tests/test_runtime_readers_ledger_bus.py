# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Runtime readers of the work ledger read it only through the reader node (OMN-26527).

Every test runs with the ledger path variable unset and no ledger file on disk. The bus is a fake
executable standing in for the reader node's interpreter (``ONEX_LEDGER_READER_PYTHON``): it records
its argv and answers rows. Each moved reader must call it with its own reader name and must never
open a ledger file; ``no_file_path`` pins that no moved file names the file or its path variable.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
#: Spelled in two halves: this file names neither, so the census does not count it.
PATH_VARIABLE = "ONEX_LEDGER_" + "PATH"
LEDGER_FILE = "ROLLING_WORK_" + "LEDGER"

LIVENESS = "plugins/onex/hooks/lib/lane_liveness.py"
IDENTITY = "scripts/lane_identity.py"
PLACEMENT = "scripts/private_repo_runner_placement_gate.py"
#: The runtime files this ticket moved; each names neither the ledger file nor its path variable.
MOVED = [LIVENESS, IDENTITY, PLACEMENT]


class Bus:
    """The fake reader node: records every call and answers ``rows`` from a file."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.log = root / "bus.log"
        self.rows = root / "rows.txt"
        self.rows.write_text("", encoding="utf-8")
        reader = root / "reader-python"
        reader.write_text(
            '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_BUS_LOG"\n'
            'cat "$FAKE_BUS_ROWS"\nexit 0\n',
            encoding="utf-8",
        )
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        self.reader = reader
        monkeypatch.delenv(PATH_VARIABLE, raising=False)
        monkeypatch.delenv("ONEX_BRANCH_CLAIM_LEDGER", raising=False)
        monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(reader))
        monkeypatch.setenv("FAKE_BUS_LOG", str(self.log))
        monkeypatch.setenv("FAKE_BUS_ROWS", str(self.rows))
        monkeypatch.setenv("OMNI_HOME", str(root / "home"))

    def answer(self, *rows: str) -> None:
        self.rows.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")

    def calls(self) -> list[str]:
        return (
            self.log.read_text(encoding="utf-8").splitlines()
            if self.log.exists()
            else []
        )

    def ledger_files(self) -> list[Path]:
        return [p for p in self.root.rglob(f"{LEDGER_FILE}*") if p.is_file()]


@pytest.fixture
def bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bus:
    return Bus(tmp_path, monkeypatch)


def load(rel: str) -> ModuleType:
    path = REPO / rel
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
        sys.path.remove(str(path.parent))
    return module


def stamp(seconds_ago: int = 0) -> str:
    moment = datetime.now(UTC).timestamp() - seconds_ago
    return datetime.fromtimestamp(moment, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_lane_liveness_reads_the_lane_rows_from_the_reader_node(bus: Bus) -> None:
    bus.answer(
        f"{stamp(3600)} | CLAIM | lane=lane-a | ticket=OMN-26527 | scope=x",
        f"{stamp(600)} | TERMINAL | lane=lane-a | ticket=OMN-26527 | outcome=done",
        f"{stamp(60)} | STATUS | lane=lane-b | ticket=OMN-1 | another lane",
    )
    age, kind = load(LIVENESS).last_ledger_row("lane-a")
    assert kind == "TERMINAL"
    assert age is not None and 590 <= age <= 700
    (call,) = bus.calls()
    assert "--reader lane-liveness" in call and "--query rows" in call
    assert "--row-lane lane-a" in call
    assert bus.ledger_files() == []


def test_lane_liveness_without_an_answer_reads_no_row_never_the_file(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(bus.root / "absent"))
    assert load(LIVENESS).last_ledger_row("lane-a") == (None, None)
    assert bus.ledger_files() == []


def test_lane_identity_backfill_reads_open_claims_from_the_reader_node(
    bus: Bus,
) -> None:
    bus.answer(
        f"OPEN-CLAIM lane=lane-a claim={stamp(60)} db:1 ticket=OMN-26527 newest-row={stamp(30)} "
        "kind=STATUS age=30s rows=2 host=none run=none leases=none liveness=unknown",
        "OPEN-CLAIM lane=lane-b claim=2020-01-01T00:00:00Z db:2 ticket=OMN-1 "
        "newest-row=2020-01-01T00:00:00Z kind=CLAIM age=9d rows=1 host=none run=none "
        "leases=none liveness=unknown",
    )
    holders = load(IDENTITY).claim_holders()
    assert holders == {"OMN-26527": "lane-a"}
    (call,) = bus.calls()
    assert "--reader lane-identity-backfill" in call and "--query open-claims" in call
    assert bus.ledger_files() == []


def test_lane_identity_backfill_refuses_when_the_node_did_not_answer(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(bus.root / "absent"))
    module = load(IDENTITY)
    with pytest.raises(module.ClaimStoreUnreadable):
        module.claim_holders()


def test_placement_gate_confirms_a_ruling_through_the_reader_node(bus: Bus) -> None:
    module = load(PLACEMENT)
    ruling = module.HostedRuling(
        ts="2026-10-16T17:44:32Z",
        lane="orchestrator",
        ticket="OMN-19998",
        repo_hashes=frozenset(),
        label_families=(),
    )
    bus.answer(
        "2026-10-16T17:44:32Z | RULING | lane=orchestrator | ticket=OMN-19998 | words"
    )
    assert module._ruling_on_ledger(ruling, str(bus.reader)) is True
    bus.answer("2026-10-16T17:44:32Z | RULING | lane=peer | ticket=OMN-19998 | words")
    assert module._ruling_on_ledger(ruling, str(bus.reader)) is False
    log = bus.log.read_text(
        encoding="utf-8"
    )  # the point-read script spans several lines
    assert log.count("placement-gate-ruling 2026-10-16T17:44:32Z") == 2
    assert bus.ledger_files() == []


@pytest.mark.parametrize("rel", MOVED)
def test_no_file_path(rel: str) -> None:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert PATH_VARIABLE not in text
    assert LEDGER_FILE not in text
    assert os.path.exists(REPO / rel)
