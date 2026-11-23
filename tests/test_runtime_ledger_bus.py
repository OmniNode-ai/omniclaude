# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Runtime code reads and writes the work ledger only through the bus (OMN-26508).

Every test runs with the ledger path variable unset and no ledger file on disk. The bus is a pair of
fake executables: the reader node's interpreter (``ONEX_LEDGER_READER_PYTHON``) and ``uv``, which
runs ``onex-ledger append-rows``. Each moved reader or writer must call one of them and must never
open a ledger file; ``no_file_path`` pins that no moved file names the file or its path variable.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
#: Spelled in two halves: this file names neither, so the census does not count it.
PATH_VARIABLE = "ONEX_LEDGER_" + "PATH"
LEDGER_FILE = "ROLLING_WORK_" + "LEDGER"
STAMP = "2026-11-20T10:00:00Z"
CLAIM = (
    "2026-11-23T05:00:00Z | CLAIM | lane=lane-a | ticket=OMN-26508 | "
    "worktree=omni_worktrees/OMN-26508/omniclaude | scope=x"
)
RULING = f'{STAMP} | RULING | lane=orchestrator | ticket=OMN-26508 | "approved"'

#: The moved runtime files; each names neither the ledger file nor its path variable.
MOVED = [
    "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers/handler_hook_refusal_fallback.py",
    "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers/handler_hook_refusal_lane.py",
    "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers/handler_hook_refusal_record.py",
    "src/omniclaude/nodes/node_hook_refusal_record_effect/models/model_subagent_lane_request.py",
    "plugins/onex/hooks/lib/hook_emit_bounded.py",
    "scripts/public_repo_hygiene_gate.py",
]


class Bus:
    """The fake bus: records every call and answers reads from ``rows``."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.log = root / "bus.log"
        self.rows = root / "rows.txt"
        self.appended = root / "appended.txt"
        bin_dir = root / "bin"
        bin_dir.mkdir()
        reader = bin_dir / "reader-python"
        reader.write_text(
            '#!/bin/sh\nprintf \'reader %s\\n\' "$*" >> "$FAKE_BUS_LOG"\n'
            'cat "$FAKE_BUS_ROWS"\nexit 0\n',
            encoding="utf-8",
        )
        uv = bin_dir / "uv"
        uv.write_text(
            '#!/bin/sh\nprintf \'uv %s\\n\' "$*" >> "$FAKE_BUS_LOG"\n'
            'cat >> "$FAKE_BUS_APPENDED"\nexit 0\n',
            encoding="utf-8",
        )
        for tool in (reader, uv):
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
        self.rows.write_text("", encoding="utf-8")
        self.home = root / "home"
        self.home.mkdir()
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "OMNI_HOME": str(self.home),
            "OMNIBASE_INTERNAL_HOME": str(root / "internal"),
            "ONEX_LEDGER_READER_PYTHON": str(reader),
            "FAKE_BUS_LOG": str(self.log),
            "FAKE_BUS_ROWS": str(self.rows),
            "FAKE_BUS_APPENDED": str(self.appended),
        }
        (root / "internal").mkdir()
        (root / "internal" / "pyproject.toml").write_text("[project]\nname='x'\n")
        monkeypatch.delenv(PATH_VARIABLE, raising=False)
        for key, value in self.env.items():
            monkeypatch.setenv(key, value)

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
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = (
        module  # a dataclass resolves its own module while it executes
    )
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_refusal_lane_open_claims_read_the_reader_node(bus: Bus) -> None:
    bus.answer(CLAIM)
    module = load(MOVED[1])
    claims = module.open_claims(bus.env)
    assert [c["lane"] for c in claims] == ["lane-a"]
    (call,) = bus.calls()
    assert "--reader hook-refusal-lane" in call and "--query rows" in call
    assert "--kind CLAIM" in call and "--kind TERMINAL" in call
    assert bus.ledger_files() == []


def test_refusal_lane_with_a_terminal_leaves_no_open_claim(bus: Bus) -> None:
    bus.answer(
        CLAIM,
        "2026-11-23T05:30:00Z | TERMINAL | lane=lane-a | ticket=OMN-26508 | outcome=done",
    )
    assert load(MOVED[1]).open_claims(bus.env) == []


def test_fallback_row_goes_through_append_rows(bus: Bus) -> None:
    module = load(MOVED[0])
    request = SimpleNamespace(
        guard="g",
        reason="r",
        detail="d",
        hooks_lib=str(REPO / "plugins/onex/hooks/lib"),
        import_error="boom",
        interpreters=("python3",),
    )
    assert module.write_fallback_row(request, bus.env) == 0
    (call,) = bus.calls()
    assert call.startswith("uv ") and "onex-ledger append-rows" in call
    assert "| FRICTION |" in bus.appended.read_text(encoding="utf-8")
    assert bus.ledger_files() == []


def test_refusal_record_append_row_goes_through_append_rows(bus: Bus) -> None:
    module = load(MOVED[2])
    row = "2026-11-23T05:00:00Z | FRICTION | lane=l | x"
    assert module.append_row(row, project=bus.root / "internal", timeout="30s") is True
    (call,) = bus.calls()
    assert "onex-ledger append-rows" in call and "--append" not in call
    assert bus.appended.read_text(encoding="utf-8") == row + "\n"
    assert bus.ledger_files() == []


def test_alarm_row_goes_through_append_rows(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", [str(REPO / "plugins/onex/hooks/lib"), *sys.path])
    module = load(MOVED[4])
    assert module.record_undelivered_alarm("category", "text", "why") is True
    (call,) = bus.calls()
    assert call.startswith("uv ") and "onex-ledger append-rows" in call
    assert "| STATUS | lane=hook-emit-alarm | state=ALERT |" in bus.appended.read_text()
    assert bus.ledger_files() == []


def test_hygiene_gate_friction_row_goes_through_append_rows(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEX_LEDGER_RELAY_OUTBOX", raising=False)
    monkeypatch.delenv("ONEX_LEDGER_APPEND_TOOL", raising=False)
    module = load(MOVED[5])
    row = "2026-11-23T05:00:00Z | FRICTION | lane=l | existing=OMN-18030 | cost=~1 lane-minutes | t"
    assert module._append_ledger_row(row) is True
    (call,) = bus.calls()
    assert "onex-ledger append-rows" in call and "--append" not in call
    assert bus.appended.read_text(encoding="utf-8") == row + "\n"
    assert bus.ledger_files() == []


@pytest.mark.parametrize("rel", MOVED)
def test_no_file_path(rel: str) -> None:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert PATH_VARIABLE not in text
    assert LEDGER_FILE not in text


def test_census_table_drops_the_moved_files() -> None:
    ratchet = yaml.safe_load(
        (REPO / "config" / "ledger_file_census_ratchet.yaml").read_text(
            encoding="utf-8"
        )
    )
    table = ratchet["files"]["omniclaude"]
    assert [rel for rel in MOVED if rel in table] == []
    assert ratchet["ratchet"]["omniclaude"] == len(table) <= 55
