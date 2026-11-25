# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared fixtures for the script suites.

WHY A LANE-IDENTITY WORKSPACE IS A SHARED FIXTURE (OMN-18800). The arming verbs
refuse to write a hook naming any `lane_identity.py` but the registry's
canonical one, `<OMNI_HOME>/omniclaude/scripts/lane_identity.py`. That refusal
is the fix for an arming run from a per-ticket worktree copy that left all 27
canonical clones naming a path the worktree prune deletes.

It follows that a test which arms anything has to say WHICH registry it is
arming, and the only way to say so is `OMNI_HOME`. Deliberately no override
variable exists for the module path: one would be the same hole under a new
name, since a lane invoking the verb from the wrong copy is exactly who would
reach for it. So the seam is this fixture, and it is a statement about the
workspace rather than an exemption from the check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import lane_identity as li


def link_canonical_module(root: Path) -> Path:
    """Make `root` a registry whose canonical lane-identity module is this one.

    A SYMLINK to the module under test, so the fixture registry and the source
    tree are one file with two spellings. That is what the suites need: the
    installed hook is baked with the registry's spelling, which is the path the
    workspace reconciler and the drift finding both name, while the behaviour
    under test is the checkout's own code and not a stale copy of it.
    """
    canonical = li.canonical_module_path(root)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    if not canonical.exists():
        canonical.symlink_to(Path(li.__file__).resolve())
    return canonical


@pytest.fixture
def lane_registry_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway registry root, with `OMNI_HOME` pointed at it.

    `monkeypatch` rather than a plain `os.environ` write so the ambient
    workspace is restored afterwards: a leaked `OMNI_HOME` would aim a later
    test's arming at the operator's real registry, which is the one directory
    a test must never write a hook into.
    """
    root = tmp_path / "registry"
    root.mkdir(parents=True, exist_ok=True)
    link_canonical_module(root)
    monkeypatch.setenv(li.WORKSPACE_ENV, str(root))
    assert os.environ[li.WORKSPACE_ENV] == str(root)
    return root


# The gh shim's lane read guard (OMN-20911) walks the caller's ancestors with
# `ps -o ppid= -o comm=`, and a suite run from a Claude Code session has Claude
# Code among its real ancestors while the same suite in CI does not. A suite
# that means "not a lane" or "a lane by ancestry" says so by putting this fake
# ps ahead of the real one: it answers that ancestry query with one parent and
# init, and hands every other ps query to the real ps unchanged.
def install_ancestry_ps(bin_dir: Path, ancestor_comm: str = "/usr/sbin/cron") -> Path:
    ps = bin_dir / "ps"
    ps.write_text(
        "#!/bin/bash\n"
        'case " $* " in\n'
        f"  *\" comm= \"*) printf '1 %s\\n' {_sh_quote(ancestor_comm)}; exit 0 ;;\n"
        "esac\n"
        'for _p in /bin/ps /usr/bin/ps; do [ -x "$_p" ] && exec "$_p" "$@"; done\n'
        "exit 1\n"
    )
    ps.chmod(0o755)
    return ps


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# A stand-in work-ledger reader node (OMN-26508)
# ---------------------------------------------------------------------------

#: The dispatch venv interpreter, as the scripts that read the ledger from the work-ledger reader
#: node run it: ``<python> -I -c <program> <reader> <since> <kind>...``. This one answers from the
#: rows file FAKE_LEDGER_ROWS names (the rows of the kinds asked for), logs the reader name, and
#: exits with FAKE_LEDGER_READER_EXIT when that is set.
_FAKE_LEDGER_READER = """#!{python}
import json, os, sys
reader, since, kinds = sys.argv[4], sys.argv[5], sys.argv[6:]
with open(os.environ["FAKE_LEDGER_READER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps([reader, since, kinds]) + "\\n")
code = os.environ.get("FAKE_LEDGER_READER_EXIT")
if code:
    sys.stderr.write("reader unavailable\\n")
    sys.exit(int(code))
for raw in open(os.environ["FAKE_LEDGER_ROWS"], encoding="utf-8").read().splitlines():
    cells = [c.strip() for c in raw.split(" | ")]
    if len(cells) >= 2 and (not kinds or cells[1] in kinds):
        print(raw)
"""


class FakeLedgerReader:
    """The rows the reader node answers, set per test; no ledger file exists anywhere."""

    def __init__(self, rows_file: Path, log_file: Path) -> None:
        self.rows_file = rows_file
        self.log_file = log_file

    def set_rows(self, *rows: str) -> None:
        self.rows_file.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")

    def calls(self) -> list[list[object]]:
        import json

        if not self.log_file.exists():
            return []
        return [json.loads(line) for line in self.log_file.read_text().splitlines()]


@pytest.fixture
def ledger_reader(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> FakeLedgerReader:
    """Point ``ONEX_LEDGER_READER_PYTHON`` at a stand-in reader that answers no rows."""
    import sys

    # Its own directory, never the test's tmp_path: a test may count what lies under that.
    scratch = tmp_path_factory.mktemp("fake-ledger-reader")
    interpreter = scratch / "python"
    interpreter.write_text(
        _FAKE_LEDGER_READER.format(python=sys.executable), encoding="utf-8"
    )
    interpreter.chmod(0o755)
    rows = scratch / "rows.txt"
    rows.write_text("", encoding="utf-8")
    log = scratch / "reader.log"
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(interpreter))
    monkeypatch.setenv("FAKE_LEDGER_ROWS", str(rows))
    monkeypatch.setenv("FAKE_LEDGER_READER_LOG", str(log))
    monkeypatch.delenv("FAKE_LEDGER_READER_EXIT", raising=False)
    monkeypatch.delenv("ONEX_LEDGER_" + "PATH", raising=False)
    return FakeLedgerReader(rows, log)
