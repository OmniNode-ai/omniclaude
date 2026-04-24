# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the team-lead foreground guard PreToolUse hook (OMN-7843).

Bypass paths that must all be verified:
  1. Guard disabled (TEAM_LEAD_FOREGROUND_BLOCK unset) → allow
  2. Kill-switch env var (ONEX_TEAM_LEAD_GUARD_DISABLE=1) → allow
  3. Kill-switch file marker → allow
  4. Subagent (CLAUDE_AGENT_ID set) → allow
  5. No matching team / empty team / lead-only team → allow

Block path:
  * Enabled + lead session + ≥1 non-lead worker + blocked tool → exit 2

Also verifies:
  * Non-matcher tools (e.g., SendMessage) always allowed even when guard fires
  * Malformed JSON payload fails open (exit 0)
  * Missing CLAUDE_SESSION_ID fails open
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

import team_lead_foreground_guard as tlg  # noqa: E402


def _run(payload: Any) -> tuple[str, int]:
    """Invoke ``tlg.main()`` with ``payload`` as stdin JSON; return (stdout, exit_code)."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(raw)), patch("sys.stdout", captured):
        exit_code = tlg.main()
    return captured.getvalue().strip(), exit_code


@pytest.fixture
def teams_root(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Isolate the teams root and a fake HOME so kill-switch file doesn't leak."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    root = fake_home / ".claude" / "teams"
    root.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_TEAMS_ROOT", str(root))
    # Clean all relevant env vars by default; individual tests set what they need.
    monkeypatch.delenv(tlg.ENV_ENABLE, raising=False)
    monkeypatch.delenv(tlg.ENV_KILL_SWITCH, raising=False)
    monkeypatch.delenv(tlg.ENV_AGENT_ID, raising=False)
    monkeypatch.delenv(tlg.ENV_SESSION_ID, raising=False)
    return root


def _write_team(
    root: pathlib.Path,
    *,
    name: str,
    lead_session: str,
    lead_agent: str = "team-lead@X",
    workers: int = 0,
) -> pathlib.Path:
    cfg_dir = root / name
    cfg_dir.mkdir()
    members = [
        {
            "agentId": lead_agent,
            "name": "team-lead",
            "agentType": "team-lead",
        }
    ]
    for i in range(workers):
        members.append(
            {
                "agentId": f"worker-{i}@{name}",
                "name": f"worker-{i}",
                "agentType": "worker",
            }
        )
    cfg = {
        "name": name,
        "leadAgentId": lead_agent,
        "leadSessionId": lead_session,
        "members": members,
    }
    path = cfg_dir / "config.json"
    path.write_text(json.dumps(cfg))
    return path


class TestBypassPaths:
    """All five documented bypass paths must short-circuit to exit 0."""

    def test_guard_disabled_by_default(self, teams_root: pathlib.Path) -> None:
        """TEAM_LEAD_FOREGROUND_BLOCK unset → guard is a no-op."""
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_kill_switch_env_var(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ONEX_TEAM_LEAD_GUARD_DISABLE=1 always wins, even with enable flag on."""
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        monkeypatch.setenv(tlg.ENV_KILL_SWITCH, "1")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_kill_switch_file_marker(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Presence of ~/.claude/omniclaude-team-lead-guard-disabled disables guard."""
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        marker = pathlib.Path.home() / ".claude" / "omniclaude-team-lead-guard-disabled"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("disabled")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_subagent_bypass(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_AGENT_ID set → subagent; must bypass regardless of team state."""
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        monkeypatch.setenv(tlg.ENV_AGENT_ID, "worker-abc@team-xyz")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_no_active_team(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No config.json matches session → allow (generous default)."""
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-nonexistent")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_lead_only_team(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Team where member list is just the lead → no workers → allow."""
        _write_team(teams_root, name="solo", lead_session="sess-1", workers=0)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        out, code = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert code == 0
        assert out == "{}"

    def test_missing_session_id(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No CLAUDE_SESSION_ID → cannot identify lead → allow."""
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        # ENV_SESSION_ID intentionally unset
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"

    def test_missing_teams_root(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CLAUDE_TEAMS_ROOT points at a non-existent dir → allow."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv(
            "CLAUDE_TEAMS_ROOT", str(tmp_path / "does" / "not" / "exist")
        )
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"


class TestBlockPath:
    """Guard enabled + active worker team → blocked tools must exit 2."""

    @pytest.fixture(autouse=True)
    def _enabled(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=3)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")

    @pytest.mark.parametrize("tool", sorted(tlg.BLOCK_TOOLS))
    def test_blocks_matcher_tool(self, tool: str) -> None:
        payload: dict[str, Any] = {"tool_name": tool, "tool_input": {}}
        if tool == "Bash":
            payload["tool_input"] = {"command": "ls"}
        elif tool in {"Edit", "Write"} or tool == "Read":
            payload["tool_input"] = {"file_path": "/tmp/x"}
        elif tool in {"Glob", "Grep"}:
            payload["tool_input"] = {"pattern": "*"}

        out, code = _run(payload)
        assert code == 2, f"{tool} should have been blocked"
        msg = json.loads(out)
        assert msg["decision"] == "block"
        assert "t1" in msg["reason"]
        assert "3" in msg["reason"]  # worker count surfaced

    @pytest.mark.parametrize(
        "tool", ["SendMessage", "Agent", "TaskCreate", "TaskUpdate", "Skill"]
    )
    def test_allows_orchestration_tool(self, tool: str) -> None:
        """Non-matcher tools must always pass through (delegation is the escape hatch)."""
        out, code = _run({"tool_name": tool, "tool_input": {}})
        assert code == 0
        assert out == "{}"


class TestFailOpen:
    """Defensive parsing — guard must never crash the session."""

    def test_bad_json(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=2)
        out, code = _run("{not valid json")
        assert code == 0
        assert out == "{}"

    def test_corrupt_team_config(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A garbage team config must not crash lookup — other teams still scanned."""
        (teams_root / "bad").mkdir()
        (teams_root / "bad" / "config.json").write_text("{not json")
        _write_team(teams_root, name="good", lead_session="sess-1", workers=2)
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 2  # good config still matched
        assert "good" in json.loads(out)["reason"]

    def test_members_not_a_list(
        self, teams_root: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """members field missing / wrong type → treat as zero workers → allow."""
        cfg_dir = teams_root / "weird"
        cfg_dir.mkdir()
        (cfg_dir / "config.json").write_text(
            json.dumps(
                {
                    "name": "weird",
                    "leadSessionId": "sess-1",
                    "leadAgentId": "team-lead@weird",
                    "members": "not-a-list",
                }
            )
        )
        monkeypatch.setenv(tlg.ENV_ENABLE, "true")
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"


class TestEnableFlagSemantics:
    """Only ``true``/``1``/``yes`` (case-insensitive) enables the guard."""

    @pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES"])
    def test_enable_values_accepted(
        self,
        value: str,
        teams_root: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=1)
        monkeypatch.setenv(tlg.ENV_ENABLE, value)
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        _out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 2

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "anything-else"])
    def test_enable_values_rejected(
        self,
        value: str,
        teams_root: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_team(teams_root, name="t1", lead_session="sess-1", workers=1)
        monkeypatch.setenv(tlg.ENV_ENABLE, value)
        monkeypatch.setenv(tlg.ENV_SESSION_ID, "sess-1")
        out, code = _run({"tool_name": "Edit", "tool_input": {"file_path": "/x"}})
        assert code == 0
        assert out == "{}"
