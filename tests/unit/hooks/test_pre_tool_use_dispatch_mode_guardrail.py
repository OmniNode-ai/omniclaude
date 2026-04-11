# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pre_tool_use_dispatch_mode_guardrail (OMN-7257)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniclaude.hooks.pre_tool_use_dispatch_mode_guardrail import (
    _DISABLE_ENV,
    run_guardrail,
)


def _agent_hook(
    prompt: str,
    *,
    team_name: str | None = None,
    agent_type: str | None = None,
    name: str | None = None,
) -> str:
    tool_input: dict[str, object] = {"prompt": prompt}
    if team_name is not None:
        tool_input["team_name"] = team_name
    if agent_type is not None:
        tool_input["agent_type"] = agent_type
    if name is not None:
        tool_input["name"] = name
    return json.dumps({"tool_name": "Agent", "tool_input": tool_input})


@pytest.mark.unit
class TestDispatchModeGuardrailPassThrough:
    def test_non_agent_tool_passes(self) -> None:
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        exit_code, output = run_guardrail(payload)
        assert exit_code == 0
        assert output == payload

    def test_single_ticket_single_repo_passes(self) -> None:
        exit_code, _ = run_guardrail(_agent_hook("Fix OMN-1234 in omniclaude"))
        assert exit_code == 0

    def test_agent_with_team_name_passes(self) -> None:
        prompt = "Work OMN-1 OMN-2 OMN-3 OMN-4 in omniclaude and omnibase_core"
        exit_code, _ = run_guardrail(_agent_hook(prompt, team_name="workers"))
        assert exit_code == 0

    def test_exploration_agent_passes(self) -> None:
        prompt = "Look at OMN-1 OMN-2 OMN-3 across omniclaude and omnibase_core"
        exit_code, _ = run_guardrail(_agent_hook(prompt, agent_type="Explore"))
        assert exit_code == 0

    def test_empty_prompt_passes(self) -> None:
        exit_code, _ = run_guardrail(_agent_hook(""))
        assert exit_code == 0

    def test_disabled_env_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(_DISABLE_ENV, "1")
        prompt = "Work OMN-1 OMN-2 OMN-3 across omniclaude and omnibase_core"
        exit_code, _ = run_guardrail(_agent_hook(prompt))
        assert exit_code == 0

    def test_malformed_json_passes(self) -> None:
        exit_code, output = run_guardrail("not json")
        assert exit_code == 0
        assert output == "not json"


@pytest.mark.unit
class TestDispatchModeGuardrailSignals:
    @pytest.fixture(autouse=True)
    def _isolated_log(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.delenv(_DISABLE_ENV, raising=False)

    def test_three_tickets_triggers_advisory(self, tmp_path: Path) -> None:
        prompt = "Drive OMN-1001, OMN-1002, and OMN-1003 to merged"
        exit_code, output = run_guardrail(_agent_hook(prompt))
        assert exit_code == 1
        payload = json.loads(output)
        assert payload["decision"] == "warn"
        assert "multi_ticket:3" in payload["reason"]

        log = (tmp_path / "dispatch-guardrail-log.ndjson").read_text()
        entry = json.loads(log.strip().splitlines()[-1])
        assert "multi_ticket:3" in entry["trigger_signals"]
        assert entry["agent_response"] == "proceeded"

    def test_duplicate_tickets_not_counted_twice(self) -> None:
        prompt = "Work OMN-1 and OMN-1 and OMN-1 again"
        exit_code, _ = run_guardrail(_agent_hook(prompt))
        assert exit_code == 0

    def test_epic_reference_triggers_advisory(self) -> None:
        prompt = "Decompose epic OMN-7253 into sub-tickets"
        exit_code, output = run_guardrail(_agent_hook(prompt))
        assert exit_code == 1
        assert "epic_reference" in json.loads(output)["reason"]

    def test_two_repos_triggers_advisory(self) -> None:
        prompt = "Refactor the shared model between omniclaude and omnibase_core"
        exit_code, output = run_guardrail(_agent_hook(prompt))
        assert exit_code == 1
        assert "multi_repo:2" in json.loads(output)["reason"]

    def test_single_repo_mentioned_twice_not_counted(self) -> None:
        prompt = "Fix OMN-1 in omniclaude — the omniclaude file needs an update"
        exit_code, _ = run_guardrail(_agent_hook(prompt))
        assert exit_code == 0

    def test_repo_substring_not_matched(self) -> None:
        prompt = "Fix OMN-1 in some-omniclaudexyz module"
        exit_code, _ = run_guardrail(_agent_hook(prompt))
        assert exit_code == 0

    def test_combined_signals_all_reported(self) -> None:
        prompt = (
            "Epic OMN-7253: ship OMN-1001, OMN-1002, OMN-1003 across "
            "omniclaude and omnibase_core"
        )
        exit_code, output = run_guardrail(_agent_hook(prompt))
        assert exit_code == 1
        reason = json.loads(output)["reason"]
        assert "multi_ticket:4" in reason
        assert "epic_reference" in reason
        assert "multi_repo:2" in reason
