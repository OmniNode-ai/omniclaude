# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook, gate and script readers of the work ledger reach it only through the reader node (OMN-26508).

Every test runs with the ledger path variable unset and no ledger file on disk. The reader node is a
fake executable standing in for the dispatch venv interpreter (``ONEX_LEDGER_READER_PYTHON``): it
records its argv and answers rows. Each moved reader must ask it under its own reader name and never
open a ledger file; a reader that does not answer must refuse, never read as an empty ledger.
``no_file_path`` pins that no moved file names the ledger file or its path variable as a path.
"""

from __future__ import annotations

import importlib.util
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as admission

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
#: Spelled in two halves: this file names neither, so the census does not count it.
PATH_VARIABLE = "ONEX_LEDGER_" + "PATH"
LEDGER_FILE = "ROLLING_WORK_" + "LEDGER"

PRUNE = "scripts/worktree_auto_prune.py"
BRANCH_CLAIM = "scripts/branch_claim.py"
HOOK = "scripts/hooks/pre-push-branch-claim"
INSTALLER = "scripts/install-hook-process-canary.sh"
PLIST = "scripts/launchd/ai.omninode.hook-process-canary.plist"
HANDLER = "src/omniclaude/nodes/node_git_effect/handlers/handler_git_admission.py"
MOVED = [PRUNE, HOOK, INSTALLER, PLIST, HANDLER]


class Bus:
    """The fake reader node: records every call and answers rows from a file."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.log = root / "bus.log"
        self.rows = root / "rows.txt"
        self.rows.write_text("", encoding="utf-8")
        reader = root / "reader-python"
        # argv: -I -c <program> <reader> <since> <kind>...  -- the reader name is argument 4.
        reader.write_text(
            '#!/bin/sh\nprintf \'%s\\n\' "$4 $5 $6 $7 $8 $9" >> "$FAKE_BUS_LOG"\n'
            'cat "$FAKE_BUS_ROWS"\nexit 0\n',
            encoding="utf-8",
        )
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        self.reader = reader
        monkeypatch.delenv(PATH_VARIABLE, raising=False)
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
    moment = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# worktree_auto_prune.py
# ---------------------------------------------------------------------------


def test_worktree_prune_reads_claims_from_the_reader_node(bus: Bus) -> None:
    prune = load(PRUNE)
    bus.answer(
        f"{stamp(3600)} | CLAIM | lane=lane-a | ticket=OMN-1234 | started",
        f"{stamp(60)} | CLAIM | lane=lane-b | ticket=OMN-1234 | also started",
        f"{stamp(30)} | TERMINAL | lane=lane-a | ticket=OMN-1234 | landed",
    )
    claims = prune.parse_ledger_claims(prune.read_ledger_rows())
    has_terminal, open_claims = claims["OMN-1234"]
    assert has_terminal is True
    assert [c.lane for c in open_claims] == ["lane-b"]
    (call,) = bus.calls()
    assert call.startswith("worktree-auto-prune-claims ")
    assert call.strip().endswith("CLAIM TERMINAL")
    assert bus.ledger_files() == []


def test_worktree_prune_unanswered_reader_refuses_the_run(
    bus: Bus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    """An unreadable ledger is never an empty one: the run exits 2 and removes nothing."""
    prune = load(PRUNE)
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(bus.root / "absent-python"))
    root = tmp_path / "omni_worktrees"
    root.mkdir()
    code = prune.main(
        ["--worktrees-root", str(root), "--no-fetch", "--no-tracker", "--no-pr-state"]
    )
    assert code == 2
    assert "ledger not readable" in capsys.readouterr().err


def test_worktree_prune_takes_no_ledger_file_argument() -> None:
    prune = load(PRUNE)
    with pytest.raises(SystemExit):
        prune.build_parser().parse_args(["--ledger", "/nowhere/ledger.md"])


# ---------------------------------------------------------------------------
# the git admission handler's ruling re-read
# ---------------------------------------------------------------------------


def test_ruling_reread_asks_the_reader_node_never_a_file(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(bus.root / "state"))
    bus.answer(
        f"{stamp(600)} | CLAIM | lane=census-lane | ticket=OMN-26508 | actor=x | worktree=none | s"
    )
    environ = {
        **os.environ,
        "ONEX_LANE": "census-lane",
        "ONEX_STATE_DIR": str(bus.root / "state"),
    }
    assert admission.ruling_reread_refusal(environ) is None
    calls = bus.calls()
    assert calls and all(c.startswith("git-admission-ruling-reread ") for c in calls)
    assert bus.ledger_files() == []


def test_ruling_reread_unanswered_reader_blocks_the_publish(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    environ = {
        **os.environ,
        "ONEX_LANE": "census-lane",
        "ONEX_STATE_DIR": str(bus.root / "state"),
        "ONEX_LEDGER_READER_PYTHON": str(bus.root / "absent-python"),
    }
    reason = admission.ruling_reread_refusal(environ) or ""
    assert "could not be verified" in reason


# ---------------------------------------------------------------------------
# branch_claim.py check, as the pre-push hook runs it
# ---------------------------------------------------------------------------


def _branch_claim(bus: Bus, *args: str) -> subprocess.CompletedProcess[str]:
    message = bus.root / "message.txt"
    message.write_text(
        "fix(OMN-9999): a change\n\nOnex-Lane: alpha\n", encoding="utf-8"
    )
    return subprocess.run(
        [
            sys.executable,
            str(REPO / BRANCH_CLAIM),
            "check",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(message),
            "--mode",
            "refuse",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=bus.root,
        env=os.environ.copy(),
    )


def test_branch_claim_check_reads_its_store_from_the_reader_node(bus: Bus) -> None:
    bus.answer(
        f"{stamp(7200)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it",
    )
    done = _branch_claim(bus)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "branch-claim:" in done.stdout
    (call,) = bus.calls()
    assert call.startswith("branch-claim-pre-push ")
    assert bus.ledger_files() == []


def test_branch_claim_check_unanswered_reader_did_not_run(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(bus.root / "absent-python"))
    done = _branch_claim(bus)
    assert done.returncode == 2
    assert "THE CHECK DID NOT RUN" in done.stderr


# ---------------------------------------------------------------------------
# no file path
# ---------------------------------------------------------------------------

#: The ledger file's name followed by a line number or a timestamp is a citation, not a path.
_CITATION = re.compile(re.escape(LEDGER_FILE) + r"(\.md)?(:\d+|@)")


@pytest.mark.parametrize("rel", MOVED)
def test_no_file_path_the_moved_files_name_neither_the_file_nor_its_variable(
    rel: str,
) -> None:
    text = (REPO / rel).read_text(encoding="utf-8")
    assert PATH_VARIABLE not in text, rel
    for line in text.splitlines():
        if LEDGER_FILE in line:
            assert _CITATION.search(line), f"{rel}: {line.strip()}"


def test_no_file_path_the_hook_and_the_installer_pass_no_ledger_argument() -> None:
    hook = (REPO / HOOK).read_text(encoding="utf-8")
    assert "--ledger" not in hook
    assert "ONEX_BRANCH_CLAIM_LEDGER" not in hook
    installer = (REPO / INSTALLER).read_text(encoding="utf-8")
    assert "--ledger" not in installer
    assert "__LEDGER__" not in installer
    assert "__LEDGER__" not in (REPO / PLIST).read_text(encoding="utf-8")
