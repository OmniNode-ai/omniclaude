# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21020 AC1: the lane GitHub read check writes one refusal row per refusal.

The block in ``pre_tool_use_bash_guards.sh`` (OMN-20916) sits ahead of the seven sourced
guards, so none of their ``hook_record_refusal`` calls can see its refusals. Each test runs
the registered entrypoint exactly as Claude Code does, with a scratch registry root whose
ledger is written through a stand-in for the locked writer, and reads the row back.

A refusing fixture yields exactly one ``class=refusal`` row carrying the gate's own
``guard=`` and ``reason=``; an allowed fixture yields none. Dedupe and suppression stay the
recorder's, so each test uses its own scratch state directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"

GUARD = "pre_tool_use_lane_github_read_guard"

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


class Scratch:
    """A scratch registry root with a ledger and a locked-writer stand-in."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.home = tmp_path / "registry_root"
        self.ledger = self.home / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text("# ledger\n", encoding="utf-8")
        self.project = project = tmp_path / "ledger_writer"
        project.mkdir()
        (project / "pyproject.toml").write_text("")
        stub = tmp_path / "uv"
        stub.write_text(_FAKE_LOCKER, encoding="utf-8")
        stub.chmod(0o755)

    def env(self, *, lane: bool) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(
                ("ONEX_", "CLAUDE_", "CODEX_", "GIT_", "GH_", "GITHUB_")
            )
        }
        env.update(
            PATH=f"{self.tmp}:" + os.environ.get("PATH", "/usr/bin:/bin"),
            OMNI_HOME=str(self.home),
            OMNIBASE_INTERNAL_HOME=str(self.project),
            ONEX_STATE_DIR=str(self.tmp / "state"),
            ONEX_HOOK_LOG=str(self.tmp / "hooks.log"),
            ONEX_HOOK_REFUSAL_STATE_DIR=str(self.tmp / "refusal_state"),
            CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
            CLAUDE_PROJECT_DIR=str(self.home),
            CLAUDE_CODE_ENTRYPOINT="cli",
            CLAUDECODE="1",
            PLUGIN_PYTHON_BIN=sys.executable,
            PYTHON_CMD=sys.executable,
            OMNICLAUDE_MODE="full",
            HOME=str(self.tmp),
            TMPDIR=str(self.tmp),
        )
        if lane:
            env["ONEX_LANE"] = "fixture-lane-omn21020"
        return env

    def rows(self) -> list[str]:
        return [
            line
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if "class=refusal" in line
        ]

    def run(self, payload: str, *, lane: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(HOOK)],
            input=payload,
            env=self.env(lane=lane),
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )

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


def _payload(tool_name: str, tool_input: dict[str, str]) -> str:
    return json.dumps(
        {
            "session_id": "fixture-session",
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "cwd": str(ROOT),
        }
    )


@pytest.fixture
def scratch(tmp_path: Path) -> Scratch:
    return Scratch(tmp_path)


MCP_READ = _payload("mcp__github__pull_request_read", {"owner": "o", "repo": "r"})

REFUSING = [
    pytest.param(
        MCP_READ,
        "lane-github-read-mcp-tool",
        id="mcp_tool",
    ),
    pytest.param(
        _payload("Bash", {"command": "curl -sS https://api.github.com/user"}),
        "lane-github-read-raw-api",
        id="raw_api",
    ),
    pytest.param(
        _payload(
            "Bash",
            {"command": "/opt/homebrew/bin/gh pr list --repo OmniNode-ai/omniclaude"},
        ),
        "lane-github-read-real-gh",
        id="real_gh",
    ),
]


@pytest.mark.parametrize(("payload", "reason"), REFUSING)
def test_refusal_row_one_row_per_lane_read_refusal(
    scratch: Scratch, payload: str, reason: str
) -> None:
    result = scratch.run(payload, lane=True)
    assert result.returncode == 2, (result.stdout, result.stderr)
    row = scratch.wait_for_rows(1)[0]
    assert "| FRICTION |" in row
    assert _cell(row, "class") == "refusal"
    assert _cell(row, "guard") == GUARD
    assert _cell(row, "reason") == reason
    # Settle, then prove it stayed one row: the writer's dedupe, not a second call.
    time.sleep(0.5)
    assert len(scratch.rows()) == 1


def test_refusal_row_unjudgeable_call_is_recorded_too(scratch: Scratch) -> None:
    """The fail-closed branch refuses as well, so it writes its row as well."""
    result = scratch.run('{"tool_name":"mcp__github__pull_request_read"', lane=True)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "could not judge" in result.stdout
    row = scratch.wait_for_rows(1)[0]
    assert _cell(row, "guard") == GUARD
    assert _cell(row, "reason") == "lane-github-read-check-could-not-judge"


def test_refusal_row_allowed_calls_write_none(scratch: Scratch) -> None:
    # The operator's own session reading GitHub, and a lane's call tripping no pre-filter.
    operator = scratch.run(
        _payload("mcp__github__pull_request_read", {"owner": "o", "repo": "r"}),
        lane=False,
    )
    assert operator.returncode == 0, (operator.stdout, operator.stderr)
    lane_write = scratch.run(
        _payload("Bash", {"command": "curl -X POST https://api.github.com/x"}),
        lane=True,
    )
    assert lane_write.returncode == 0, (lane_write.stdout, lane_write.stderr)
    time.sleep(0.5)
    assert scratch.rows() == []
    # Positive control: the same scratch ledger does take a row from a refusal.
    refused = scratch.run(MCP_READ, lane=True)
    assert refused.returncode == 2
    assert len(scratch.wait_for_rows(1)) == 1
