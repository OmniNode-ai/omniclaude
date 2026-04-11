# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for overseer_foreground_block PreToolUse guard (OMN-8376).

Verifies the guard:
  * Allows everything when the flag file is absent (fast path).
  * Blocks Bash mutating commands (``gh pr merge``, ``git push``) when the
    flag is present.
  * Blocks Edit/Write targeting paths under ``$OMNI_HOME``.
  * Passes through Edit/Write targeting paths outside ``$OMNI_HOME``.
  * Surfaces ``contract_path`` and ``active_phase`` from the flag in the
    block reason.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from typing import Any
from unittest.mock import patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import overseer_foreground_block as ofb  # noqa: E402


def _run(payload: dict[str, Any]) -> tuple[str, int]:
    raw = json.dumps(payload)
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(raw)), patch("sys.stdout", captured):
        exit_code = ofb.main()
    return captured.getvalue().strip(), exit_code


@pytest.fixture
def omni_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    root = tmp_path / "omni_home"
    root.mkdir()
    monkeypatch.setenv("OMNI_HOME", str(root))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("ONEX_STATE_DIR", str(state_dir))
    return root


@pytest.fixture
def active_flag(omni_home: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    flag = (
        pathlib.Path(sys.modules["os"].environ["ONEX_STATE_DIR"])
        / "overseer-active.flag"
    )
    flag.write_text(
        "contract_path: /abs/tonight.yaml\nactive_phase: wave-2\nstarted_at: 2026-04-11T07:00:00Z\n"
    )
    return flag


class TestFlagAbsent:
    def test_bash_allowed_when_flag_missing(self, omni_home: pathlib.Path) -> None:
        out, code = _run(
            {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 123 --auto"}}
        )
        assert code == 0
        assert out == "{}"

    def test_edit_allowed_when_flag_missing(self, omni_home: pathlib.Path) -> None:
        out, code = _run(
            {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(omni_home / "repo/f.py")},
            }
        )
        assert code == 0
        assert out == "{}"


class TestFlagPresent:
    def test_bash_gh_pr_merge_blocked(self, active_flag: pathlib.Path) -> None:
        out, code = _run(
            {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 123 --auto"}}
        )
        assert code == 2
        payload = json.loads(out)
        assert payload["decision"] == "block"
        assert "/abs/tonight.yaml" in payload["reason"]
        assert "wave-2" in payload["reason"]
        assert "rm " in payload["reason"]

    def test_bash_git_push_blocked(self, active_flag: pathlib.Path) -> None:
        out, code = _run(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD"}}
        )
        assert code == 2
        assert json.loads(out)["decision"] == "block"

    def test_bash_absolute_path_under_omni_home_blocked(
        self, active_flag: pathlib.Path, omni_home: pathlib.Path
    ) -> None:
        target = omni_home / "omniclaude"
        target.mkdir()
        out, code = _run(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"ls {target}", "cwd": "/tmp"},
            }
        )
        assert code == 2

    def test_bash_harmless_ls_tmp_allowed(
        self, active_flag: pathlib.Path, omni_home: pathlib.Path
    ) -> None:
        out, code = _run(
            {"tool_name": "Bash", "tool_input": {"command": "ls /tmp", "cwd": "/tmp"}}
        )
        assert code == 0
        assert out == "{}"

    def test_edit_under_omni_home_blocked(
        self, active_flag: pathlib.Path, omni_home: pathlib.Path
    ) -> None:
        target = omni_home / "omniclaude" / "f.py"
        target.parent.mkdir(parents=True)
        target.write_text("")
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}}
        )
        assert code == 2

    def test_edit_outside_omni_home_allowed(
        self, active_flag: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        other = tmp_path / "elsewhere" / "f.py"
        other.parent.mkdir(parents=True)
        other.write_text("")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": str(other)}})
        assert code == 0
        assert out == "{}"

    def test_read_tool_not_in_block_list(self, active_flag: pathlib.Path) -> None:
        # Read is not in BLOCK_TOOLS — guard ignores it entirely.
        out, code = _run(
            {"tool_name": "Read", "tool_input": {"file_path": "/anywhere/f.py"}}
        )
        assert code == 0
        assert out == "{}"


class TestFlagParsing:
    def test_parse_flag_extracts_fields(self, tmp_path: pathlib.Path) -> None:
        flag = tmp_path / "overseer-active.flag"
        flag.write_text(
            'contract_path: "/x/y.yaml"\nactive_phase: phase-3\nstarted_at: 2026-04-11T07:00:00Z\n'
        )
        contract, phase = ofb._parse_flag(flag)
        assert contract == "/x/y.yaml"
        assert phase == "phase-3"

    def test_parse_flag_missing_fields_returns_defaults(
        self, tmp_path: pathlib.Path
    ) -> None:
        flag = tmp_path / "flag.yaml"
        flag.write_text("# empty\n")
        contract, phase = ofb._parse_flag(flag)
        assert contract == "<unknown>"
        assert phase == "<unknown>"
