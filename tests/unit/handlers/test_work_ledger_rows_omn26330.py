# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The shared work-ledger rows client answers from the reader node and never from a file (OMN-26330)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.handlers.work_ledger_rows import (
    LedgerRowsUnavailable,
    read_rows,
    reader_interpreter,
)

pytestmark = pytest.mark.unit


def _reader(tmp_path: Path, body: str) -> str:
    script = tmp_path / "reader"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def test_the_read_names_the_reader_the_window_and_each_kind(tmp_path: Path) -> None:
    log = tmp_path / "argv.log"
    reader = _reader(tmp_path, f'echo "$*" > "{log}"\necho "row one"')
    rows = read_rows(
        "some-reader", 48, ("CLAIM", "ACK"), interpreter=reader, environ={}
    )
    assert rows == ["row one"]
    argv = log.read_text(encoding="utf-8")
    assert "-m omnimarket.nodes.node_work_ledger_reader_effect" in argv
    assert "--reader some-reader --query rows --window-hours 48" in argv
    assert "--kind CLAIM --kind ACK" in argv


@pytest.mark.parametrize("code", [2, 3, 69])
def test_a_reader_that_did_not_answer_is_unavailable(tmp_path: Path, code: int) -> None:
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, interpreter=_reader(tmp_path, f"exit {code}"), environ={})


def test_a_stale_answer_still_carries_its_rows(tmp_path: Path) -> None:
    reader = _reader(tmp_path, "echo row\nexit 1")
    assert read_rows("r", 1, interpreter=reader, environ={}) == ["row"]


def test_a_missing_interpreter_is_unavailable() -> None:
    with pytest.raises(LedgerRowsUnavailable):
        read_rows("r", 1, environ={})


def test_a_read_past_the_bound_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(LedgerRowsUnavailable):
        read_rows(
            "r", 1, interpreter=_reader(tmp_path, "sleep 5"), environ={}, timeout_s=0.2
        )


def test_the_interpreter_comes_from_the_caller_then_the_host_then_the_registry(
    tmp_path: Path,
) -> None:
    venv = tmp_path / ".onex-dispatch-venv" / "bin"
    venv.mkdir(parents=True)
    python = venv / "python"
    python.write_text("", encoding="utf-8")
    python.chmod(0o755)
    env = {"OMNI_HOME": str(tmp_path)}
    assert reader_interpreter(env) == str(python)
    assert (
        reader_interpreter({**env, "ONEX_LEDGER_BUS_APPEND_COMMAND": "/bus x"})
        == "/bus"
    )
    assert reader_interpreter({**env, "ONEX_LEDGER_READER_PYTHON": "/host"}) == "/host"
    assert (
        reader_interpreter({**env, "ONEX_LEDGER_READER_PYTHON": "/host"}, "/own")
        == "/own"
    )
