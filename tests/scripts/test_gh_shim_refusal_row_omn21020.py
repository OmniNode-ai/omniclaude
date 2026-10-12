# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21020 AC1: the gh shim's lane-read and covered-write refusals write one refusal row each.

The shim refused a lane's GitHub read (OMN-20911) and a covered write (OMN-20914) into its own
call log only, a file nothing aggregates. Each refusal now also calls the refusal recorder's
shell entry (``hook_refusal.sh``), so the row reaches the rolling ledger with the gate's own
``guard=`` and ``reason=``; dedupe and suppression stay the recorder's.

Each test puts a scripted fake ``gh`` behind the shim, a scratch registry root whose ledger takes
rows through a stand-in for the locked writer, and the recorder's state in a scratch directory.
An allowed call must write none, and a refused call must still never reach the real gh.
"""

from __future__ import annotations

import re
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.scripts.conftest import install_ancestry_ps
from tests.scripts.test_gh_lane_write_guard import (
    COVERED,
    ENFORCED,
    FAKE_GH,
    UNCOVERED_WRITES,
    _install,
)

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "scripts" / "user-bin" / "gh"
SEAM = ROOT / "plugins" / "onex" / "hooks" / "lib" / "hook_refusal.sh"

READ_GUARD = "gh_shim_lane_read_guard"
WRITE_GUARD = "gh_shim_lane_write_guard"

#: A stand-in for ``uv run --project <ledger writer project> onex-ledger <ledger> --append <row>``.
_FAKE_LOCKER = (
    f"#!{sys.executable}\n"
    "import pathlib, sys\n"
    "sys.argv = sys.argv[5:]\n"
    "ledger = pathlib.Path(sys.argv[1])\n"
    "row = sys.argv[sys.argv.index('--append') + 1]\n"
    "with ledger.open('a', encoding='utf-8') as fh:\n"
    "    fh.write(row + '\\n')\n"
)


#: The two blocks of node_github_repo_write_effect's contract.yaml the shim reads, written out
#: here so no test depends on which omnimarket the host's venv pins.
def _contract() -> str:
    operations = "".join(
        f"  - name: {operation}\n"
        f'    description: "Request ModelRepoWriteRequest; replaces gh {gh_verb}. Fixture."\n'
        "    transport: rest\n"
        for gh_verb, (_argv, _scm, operation) in COVERED.items()
    )
    return (
        "operations:\n"
        + operations
        + "\nwrite_config:\n"
        + "  github_mode: dry_run\n"
        + "  github_mode_by_repository:\n"
        + f"    {ENFORCED}: enforce\n"
    )


def _exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class Box:
    """The shim's surroundings: fake gh, registry root, ledger and writer stand-in."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        conf = tmp / "config" / "omni" / "gh-gateway.env"
        conf.parent.mkdir(parents=True)
        conf.write_text("ONEX_GH_LANE_READ_STRICT_PR_LIST=1\n")
        self.workspace = tmp / "workspace"
        _install(self.workspace, contract=_contract())
        self.ledger = self.workspace / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# ledger\n", encoding="utf-8")
        project = tmp / "ledger_writer"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        realbin = tmp / "realbin"
        _exec(realbin / "gh", FAKE_GH)
        install_ancestry_ps(realbin)
        _exec(realbin / "uv", _FAKE_LOCKER)
        self.base = {
            "PATH": f"{SHIM.parent}:{realbin}:/usr/bin:/bin",
            "HOME": str(tmp / "home"),
            "XDG_CACHE_HOME": str(tmp / "cache"),
            "XDG_CONFIG_HOME": str(tmp / "config"),
            "FAKE_GH_LOG": str(tmp / "calls.jsonl"),
            "ONEX_GH_CALLS_LOG": str(tmp / "gh-calls.log"),
            "ONEX_LANDING_CONTROLLER_ROOT": str(tmp / "controller"),
            "OMNI_HOME": str(self.workspace),
            "OMNIBASE_INTERNAL_HOME": str(project),
            "ONEX_HOOK_REFUSAL_SEAM": str(SEAM),
            "ONEX_HOOK_REFUSAL_STATE_DIR": str(tmp / "refusal_state"),
            "PYTHON_CMD": sys.executable,
            "TMPDIR": str(tmp),
            "GIT_CONFIG_NOSYSTEM": "1",
            "ONEX_GH_READ_ROUTING": "0",
        }

    def gh(self, *args: str, lane: bool) -> subprocess.CompletedProcess[str]:
        env = dict(self.base)
        if lane:
            env["ONEX_LANE"] = "shim-refusal-row-lane"
        return subprocess.run(
            ["gh", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def reached_real_gh(self) -> bool:
        return Path(self.base["FAKE_GH_LOG"]).exists()

    def rows(self) -> list[str]:
        return [
            line
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if "class=refusal" in line
        ]

    def wait_for_rows(self, count: int) -> list[str]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            rows = self.rows()
            if len(rows) >= count:
                return rows
            time.sleep(0.05)
        raise AssertionError(
            f"fewer than {count} refusal rows within 20s: {self.rows()}"
        )


def _cell(row: str, key: str) -> str:
    match = re.search(rf"\| {re.escape(key)}=([^|]*?) \|", row)
    assert match, f"{key}= missing from {row}"
    return match.group(1)


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


pytestmark = pytest.mark.unit


def test_refusal_row_lane_read_writes_one_row(box: Box) -> None:
    result = box.gh("pr", "list", "--repo", "o/r", lane=True)
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20911): "), result.stderr
    assert not box.reached_real_gh()
    row = box.wait_for_rows(1)[0]
    assert "| FRICTION |" in row
    assert _cell(row, "class") == "refusal"
    assert _cell(row, "guard") == READ_GUARD
    assert _cell(row, "reason") == "lane-github-read-via-gh-shim"
    time.sleep(0.5)
    assert len(box.rows()) == 1


def test_refusal_row_lane_read_spent_fallback_budget_writes_one_row(box: Box) -> None:
    conf = box.tmp / "config" / "omni" / "gh-gateway.env"
    conf.write_text("ONEX_GH_LANE_READ_STRICT_PR_LIST=1\nONEX_GH_GATEWAY_BUDGET=0\n")
    result = box.gh("api", "user", lane=True)
    assert result.returncode == 1, result.stderr
    first = result.stderr.splitlines()[0]
    assert first.startswith("REFUSED (OMN-20911): "), result.stderr
    assert "is a GitHub read from a lane" in first
    assert "lane read fallback budget is spent" in first
    assert "ONEX_GH_GATEWAY_BUDGET=0" in first
    assert not box.reached_real_gh()
    row = box.wait_for_rows(1)[0]
    assert _cell(row, "class") == "refusal"
    assert _cell(row, "guard") == READ_GUARD
    assert _cell(row, "reason") == "lane-github-read-via-gh-shim"
    time.sleep(0.5)
    assert len(box.rows()) == 1


@pytest.mark.parametrize("gh_verb", list(COVERED), ids=str)
def test_refusal_row_covered_write_writes_one_row(box: Box, gh_verb: str) -> None:
    argv, _scm_verb, _operation = COVERED[gh_verb]
    result = box.gh(*argv, lane=True)
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20914): "), result.stderr
    assert not box.reached_real_gh()
    row = box.wait_for_rows(1)[0]
    assert _cell(row, "class") == "refusal"
    assert _cell(row, "guard") == WRITE_GUARD
    assert _cell(row, "reason") == "covered-write-via-gh-shim"
    time.sleep(0.5)
    assert len(box.rows()) == 1


def test_refusal_row_allowed_calls_write_none(box: Box) -> None:
    # The operator's own read, a lane's uncovered write, and a lane's sanctioned rate_limit read.
    operator = box.gh("pr", "list", "--repo", "o/r", lane=False)
    assert operator.returncode == 0, operator.stderr
    uncovered = box.gh(*UNCOVERED_WRITES[0], lane=True)
    assert uncovered.returncode == 0, uncovered.stderr
    rate = box.gh("api", "rate_limit", lane=True)
    assert rate.returncode == 0, rate.stderr
    time.sleep(0.5)
    assert box.rows() == []
    # Positive control: the same scratch ledger does take a row from a refusal.
    refused = box.gh("pr", "list", "--repo", "o/r", lane=True)
    assert refused.returncode == 1
    assert len(box.wait_for_rows(1)) == 1


def test_refusal_row_missing_seam_keeps_the_refusal(box: Box) -> None:
    """A recorder that cannot be reached never turns a refusal into an allow."""
    env = dict(box.base)
    env["ONEX_LANE"] = "shim-refusal-row-lane"
    env["ONEX_HOOK_REFUSAL_SEAM"] = str(box.tmp / "no-such-seam.sh")
    result = subprocess.run(
        ["gh", "pr", "list", "--repo", "o/r"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20911): ")
    assert not box.reached_real_gh()
    assert box.rows() == []
