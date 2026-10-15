# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A refusal reaches the ledger even when the recorder cannot (OMN-20883).

Three ways the OMN-18946 recorder lost a refusal after the guard had already
refused the call:

* its interpreter could not import the row module, so the only trace was one
  stderr line in hooks.log;
* the lane cell carried the dispatch ROUTE line, so the ledger row grammar
  rejected the row;
* the ledger writer rejected a row and the recorder reported it on stderr only.

Each test drives the real seam (``hook_record_refusal`` in a bash process that
sources ``error-guard.sh``) or the real recorder entry, with only the ledger
writer and, for the import failure, the interpreter replaced.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.unit

from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (
    handler_hook_refusal_lane as lane_resolver,
)
from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (
    handler_hook_refusal_record as recorder,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ERROR_GUARD = REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "error-guard.sh"

ROUTE_LINE = (
    "ROUTE: band=B2 score=9 dims=S1A1R1V2N2C1J1 dest=lab model=sonnet effort=high"
)

#: A stand-in for ``uv run --project <p> onex-ledger <ledger> --append <row>``.
_FAKE_UV = (
    f"#!{sys.executable}\n"
    "import pathlib, sys\n"
    "argv = sys.argv[5:]\n"
    "ledger = pathlib.Path(argv[1])\n"
    "row = argv[argv.index('--append') + 1]\n"
    "with ledger.open('a', encoding='utf-8') as fh:\n"
    "    fh.write(row + '\\n')\n"
)

#: An interpreter that cannot import the recorder's modules, as the guard
#: runner's did: the message is the one CPython and the recorder itself print.
_BROKEN_PYTHON = (
    "#!/bin/sh\n"
    'echo "python3: Error while finding module specification for '
    "'omniclaude.nodes.node_hook_refusal_record_effect.handlers."
    "handler_hook_refusal_record' (ModuleNotFoundError: No module named "
    "'omniclaude')\" >&2\n"
    "exit 1\n"
)

_GUARD_SHAPE = """
_OMNICLAUDE_HOOK_NAME="${TEST_HOOK_NAME}"
source "${TEST_ERROR_GUARD}"
TOOL_INFO=$(cat)
hook_record_refusal "worktree path outside canonical root: /x/y" "BLOCKED: test refusal"
trap - EXIT
exit 0
"""


class Box:
    """A scratch registry root with a ledger and a stand-in locked writer."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "registry_root"
        self.ledger = self.home / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# ledger\n", encoding="utf-8")
        project = tmp_path / "omnibase_internal"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        uv = tmp_path / "uv"
        uv.write_text(_FAKE_UV, encoding="utf-8")
        uv.chmod(0o755)
        self.project = project

    def env(self, extra: dict[str, str]) -> dict[str, str]:
        env = {
            "PATH": f"{self.tmp}:" + os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "OMNI_HOME": str(self.home),
            "OMNIBASE_INTERNAL_HOME": str(self.project),
            "ONEX_LEDGER_PATH": str(self.ledger),
            "CLAUDE_PROJECT_DIR": str(self.home),
            "ONEX_HOOK_REFUSAL_STATE_DIR": str(self.tmp / "refusal_state"),
            "ONEX_STATE_DIR": str(self.home / ".onex_state"),
            "TMPDIR": str(self.tmp),
            "TEST_ERROR_GUARD": str(ERROR_GUARD),
            "TEST_HOOK_NAME": "pre_tool_use_worktree_guard.sh",
        }
        env.update(extra)
        return env

    def refuse(self, extra_env: dict[str, str]) -> list[str]:
        """Fire one refusal through the shell seam; return the FRICTION rows."""
        result = subprocess.run(
            ["bash", "-c", _GUARD_SHAPE],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}),
            capture_output=True,
            text=True,
            check=False,
            env=self.env(extra_env),
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = [
                line
                for line in self.ledger.read_text(encoding="utf-8").splitlines()
                if "| FRICTION |" in line
            ]
            if rows:
                return rows
            time.sleep(0.05)
        raise AssertionError("no FRICTION row reached the ledger within 20s")


def _cell(row: str, key: str) -> str:
    match = re.search(rf"\| {re.escape(key)}=([^|]*?) \|", row)
    assert match, f"{key}= missing from {row}"
    return match.group(1)


def test_hook_refusal_recorder_import_failure_recorded(tmp_path: Path) -> None:
    """AC1: an interpreter that cannot import the row module still leaves a row."""
    box = Box(tmp_path)
    broken = tmp_path / "broken-python"
    broken.write_text(_BROKEN_PYTHON, encoding="utf-8")
    broken.chmod(0o755)

    rows = box.refuse({"PYTHON_CMD": str(broken), "ONEX_LANE": "omn20883-tix"})

    assert len(rows) == 1
    row = rows[0]
    assert _cell(row, "guard") == "pre_tool_use_worktree_guard.sh"
    assert _cell(row, "reason") == "recorder-import-failure"
    assert _cell(row, "class") == "refusal"
    assert _cell(row, "lane") == "omn20883-tix"
    assert _cell(row, "lane_source") == "fallback-env"
    assert "BLOCKED: test refusal" not in row  # no redactor here: detail withheld


def test_hook_refusal_recorder_prefers_plugin_python(tmp_path: Path) -> None:
    """AC1: PLUGIN_PYTHON_BIN wins over a bare ``python3`` that lacks the module."""
    box = Box(tmp_path)
    broken = tmp_path / "broken-python"
    broken.write_text(_BROKEN_PYTHON, encoding="utf-8")
    broken.chmod(0o755)
    shim = tmp_path / "python3"  # first on PATH: what the old fallback picked
    shim.write_text(_BROKEN_PYTHON, encoding="utf-8")
    shim.chmod(0o755)

    rows = box.refuse(
        {"PLUGIN_PYTHON_BIN": sys.executable, "ONEX_LANE": "omn20883-tix"}
    )

    assert len(rows) == 1
    assert _cell(rows[0], "reason") != "recorder-import-failure"
    assert _cell(rows[0], "lane_source") == "env"


@pytest.mark.parametrize(
    "value",
    [
        f"omn20883-tix\n{ROUTE_LINE}",
        f"omn20883-tix {ROUTE_LINE}",
        f"{ROUTE_LINE}\nomn20883-tix",
    ],
)
def test_hook_refusal_lane_cell_strips_route(value: str) -> None:
    """AC2: the lane cell is the lane name only, never the ROUTE line."""
    lane, source = lane_resolver.resolve_refusal_lane(
        None, env={"ONEX_LANE": value}, ledger=None
    )
    assert lane == "omn20883-tix"
    assert source == lane_resolver.LANE_SOURCE_ENV
    row = recorder.decide_row(
        guard="g",
        reason="r",
        lane=lane,
        lane_source=source,
        detail="",
        session="",
        suppressed=0,
        timestamp="2026-10-15T08:00:00Z",
    ).row
    assert "ROUTE" not in row
    assert _cell(row, "lane") == "omn20883-tix"


def test_hook_refusal_lane_cell_route_only_is_unresolved() -> None:
    lane, source = lane_resolver.resolve_refusal_lane(
        None, env={"ONEX_LANE": ROUTE_LINE}, ledger=None
    )
    assert (lane, source) == ("", lane_resolver.LANE_SOURCE_UNRESOLVED)


def test_hook_refusal_rejected_row_alerts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC3: a row the ledger writer rejects raises a STATUS ALERT row."""
    project = tmp_path / "omnibase_internal"
    project.mkdir()
    (project / "pyproject.toml").write_text("")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# ledger\n", encoding="utf-8")
    appended: list[str] = []

    def writer(argv: list[str], **kwargs: object) -> Mock:
        row = argv[argv.index("--append") + 1]
        appended.append(row)
        if "| FRICTION |" in row:
            return Mock(returncode=1, stderr="grammar: FRICTION row missing lane=")
        return Mock(returncode=0, stderr="")

    monkeypatch.setattr(recorder.subprocess, "run", writer)
    friction = recorder.decide_row(
        guard="pre_tool_use_worktree_guard.sh",
        reason="outside-root",
        lane="omn20883-tix",
        lane_source="env",
        detail="BLOCKED",
        session="",
        suppressed=0,
        timestamp="2026-10-15T08:00:00Z",
    )

    landed = recorder.append_row(
        friction.row, ledger=ledger, project=project, timeout="5s"
    )

    assert landed is False  # the dedupe state must not advance
    assert len(appended) == 2
    alert = appended[1]
    assert "| STATUS |" in alert
    assert _cell(alert, "state") == "ALERT"
    assert _cell(alert, "category") == "refusal-row-rejected"
    assert _cell(alert, "guard") == "pre_tool_use_worktree_guard.sh"
    assert _cell(alert, "dedupe") == friction.key
    assert "grammar: FRICTION row missing lane=" in alert
    assert "\n" not in alert


def test_hook_refusal_rejected_alert_does_not_recurse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rejected ALERT row is reported on stderr, never alerted on again."""
    project = tmp_path / "omnibase_internal"
    project.mkdir()
    (project / "pyproject.toml").write_text("")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# ledger\n", encoding="utf-8")
    run = Mock(return_value=Mock(returncode=1, stderr="refused"))
    monkeypatch.setattr(recorder.subprocess, "run", run)

    assert not recorder.append_row(
        "2026-10-15T08:00:00Z | FRICTION | guard=g | x",
        ledger=ledger,
        project=project,
        timeout="5s",
    )
    assert run.call_count == 2
