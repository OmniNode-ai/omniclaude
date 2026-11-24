# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Exit 1 of the work-ledger reader node is an answer only when its READER line says so (OMN-26641).

The node exits 1 for a stale answer, but a Python process that dies on an unhandled exception exits 1
too. A crash prints nothing on stdout, so reading exit 1 as "answered" turned it into zero rows: no
open claims, and a pruner that removes live worktrees. The crash output below is the recorded refusal
of the missing reader overlay (``tests/fixtures/integration_act_lane_2026_11_24/recorded.json``).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.handlers.work_ledger_rows import (
    LedgerRowsUnavailable,
    read_rows,
    reader_answered,
)

pytestmark = pytest.mark.unit

RECORDED = (
    Path(__file__).parents[2]
    / "fixtures"
    / "integration_act_lane_2026_11_24"
    / "recorded.json"
)
ROW = "2026-11-24T10:14:37Z | CLAIM | lane=some-lane | ticket=OMN-1"


def _recorded_crash() -> dict[str, object]:
    readings = json.loads(RECORDED.read_text(encoding="utf-8"))["reader_readings"]
    crash = [r for r in readings if r["exit"] == 1 and r["stdout_lines"] == 0]
    assert len(crash) == 1, "the fixture holds exactly one exit-1 crash reading"
    return crash[0]


def _reader(tmp_path: Path, stdout: str, stderr: str, code: int) -> str:
    script = tmp_path / "reader"
    out, err = tmp_path / "out.txt", tmp_path / "err.txt"
    out.write_text(stdout, encoding="utf-8")
    err.write_text(stderr, encoding="utf-8")
    script.write_text(
        f'#!/bin/sh\ncat "{out}"\ncat "{err}" >&2\nexit {code}\n', encoding="utf-8"
    )
    script.chmod(0o755)
    return str(script)


def _line(status: str, matched: int = 1) -> str:
    return (
        f"READER reader=r query=rows status={status} source=node reason=x "
        f"watermark_age_s=0 max_age_s=900 parity=unread matched={matched} file_read=no "
        "elapsed_s=0.1\n"
    )


def test_the_recorded_crash_is_unavailable_not_zero_rows(tmp_path: Path) -> None:
    crash = _recorded_crash()
    reader = _reader(tmp_path, "", f"{crash['stderr']}\n", 1)
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, interpreter=reader, environ={})


def test_a_crash_with_a_traceback_is_unavailable(tmp_path: Path) -> None:
    stderr = (
        "Traceback (most recent call last):\n"
        '  File "<frozen runpy>", line 198, in _run_module_as_main\n'
        "ModuleNotFoundError: No module named 'omnimarket'\n"
    )
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, interpreter=_reader(tmp_path, "", stderr, 1), environ={})


def test_exit_one_with_rows_and_no_reader_line_is_unavailable(tmp_path: Path) -> None:
    reader = _reader(tmp_path, f"{ROW}\n", "", 1)
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, interpreter=reader, environ={})


def test_a_stale_answer_is_unavailable(tmp_path: Path) -> None:
    reader = _reader(tmp_path, f"{ROW}\n", _line("stale"), 1)
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, interpreter=reader, environ={})


def test_exit_one_with_an_ok_reader_line_carries_its_rows(tmp_path: Path) -> None:
    reader = _reader(tmp_path, f"{ROW}\n", _line("ok"), 1)
    assert read_rows("r", 1, interpreter=reader, environ={}) == [ROW]


def test_a_declared_no_match_is_zero_rows(tmp_path: Path) -> None:
    reader = _reader(tmp_path, "", _line("no-match", 0), 1)
    assert read_rows("r", 1, interpreter=reader, environ={}) == []


def test_exit_zero_is_an_answer(tmp_path: Path) -> None:
    reader = _reader(tmp_path, f"{ROW}\n", _line("ok"), 0)
    assert read_rows("r", 1, interpreter=reader, environ={}) == [ROW]


@pytest.mark.parametrize(
    ("code", "stderr", "answered"),
    [
        (0, "", True),
        (1, "", False),
        (1, "Traceback (most recent call last):\nValueError: x\n", False),
        (1, _line("stale"), False),
        (1, _line("unreadable", 0), False),
        (1, _line("ok"), True),
        (1, _line("no-match", 0), True),
        (1, "noise\n" + _line("ok"), True),
        (1, "not a READER reader=r status=ok line\n", False),
        (3, _line("ok"), False),
        (69, _line("ok"), False),
    ],
)
def test_reader_answered_table(code: int, stderr: str, answered: bool) -> None:
    assert reader_answered(code, stderr) is answered


def _load(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPO = Path(__file__).parents[3]
# The node's only exit 1 is a stale answer, so the other clients of the reader node, which are loaded
# by path under a bare interpreter and cannot import the rule above, take exit 0 alone.


def test_the_refusal_lane_claim_read_resolves_nothing_from_a_crash(
    tmp_path: Path,
) -> None:
    refusal = _load(
        "client_hook_refusal_lane",
        "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers/handler_hook_refusal_lane.py",
    )
    for stderr, code, rows in [
        ("ValueError: x\n", 1, []),
        (_line("stale"), 1, []),
        (_line("ok"), 0, [ROW]),
    ]:
        reader = _reader(tmp_path, f"{ROW}\n", stderr, code)
        env = {"ONEX_LEDGER_READER_PYTHON": reader}
        assert refusal._claim_rows(env) == rows, (stderr, code)


def test_the_ticket_lookup_resolves_nothing_from_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniclaude.handlers.handler_ticket_ledger_lookup import rows_for_stamp

    stamp = "2026-11-24T10:14:37Z"
    crash = _reader(tmp_path, f"{stamp} | RULING | x\n", "ValueError: x\n", 1)
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", crash)
    assert rows_for_stamp("ticket-ruling", stamp, " | ") == []
    answered = _reader(tmp_path, f"{stamp} | RULING | x\n", _line("ok"), 0)
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", answered)
    assert rows_for_stamp("ticket-ruling", stamp, " | ") == [f"{stamp} | RULING | x"]
