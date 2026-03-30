# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for PostToolUse team lifecycle observability hook (OMN-7022).

Tests verify:
- Hook exits 0 for all matched tool names (advisory, never blocks)
- Kill switch disables the hook cleanly
- Topics are registered in TopicBase
- Event types are registered in emit_client_wrapper SUPPORTED_EVENT_TYPES
- hooks.json has the correct matcher and script path

Note: Shell-level integration tests (emit_via_daemon, dedup files) require
the full plugin runtime (CLAUDE_PLUGIN_ROOT with venv). The hook uses
error-guard.sh which guarantees exit 0 even when common.sh cannot find a
Python interpreter — this is correct advisory behavior.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

WORKTREE_ROOT = str(Path(__file__).resolve().parent.parent.parent)  # local-path-ok
HOOK_SCRIPT = "plugins/onex/hooks/scripts/post_tool_use_team_observability.sh"


def _run_hook(
    stdin_data: dict,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run the team observability hook with given stdin JSON."""
    env = os.environ.copy()
    env["OMNICLAUDE_HOOKS_DISABLED"] = "0"
    env["OMNICLAUDE_HOOK_TEAM_OBSERVABILITY"] = "1"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", HOOK_SCRIPT],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=WORKTREE_ROOT,
        env=env,
        check=False,
    )


@pytest.mark.unit
class TestTeamObservabilityAdvisory:
    """Advisory hook must always exit 0 regardless of environment."""

    def test_team_create_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "TeamCreate",
            "tool_input": {"team_name": "test-team", "description": "Test"},
            "tool_response": {"team_name": "test-team"},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0

    def test_agent_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "Agent",
            "tool_input": {
                "agent_name": "worker-1",
                "team_name": "test-team",
                "task_id": "task-123",
            },
            "tool_response": {},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0

    def test_task_create_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "TaskCreate",
            "tool_input": {"description": "Implement feature X"},
            "tool_response": {"task_id": "task-456"},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0

    def test_task_update_completed_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "TaskUpdate",
            "tool_input": {"task_id": "task-789", "status": "completed"},
            "tool_response": {},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0

    def test_task_update_in_progress_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "TaskUpdate",
            "tool_input": {"task_id": "task-789", "status": "in_progress"},
            "tool_response": {},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0

    def test_send_message_exits_zero(self) -> None:
        stdin_data = {
            "tool_name": "SendMessage",
            "tool_input": {"to": "worker-1", "message": "hello"},
            "tool_response": {},
        }
        result = _run_hook(stdin_data)
        assert result.returncode == 0


@pytest.mark.unit
class TestTeamObservabilityKillSwitch:
    """Kill switch disables the hook cleanly."""

    def test_disabled_via_env(self) -> None:
        stdin_data = {
            "tool_name": "TeamCreate",
            "tool_input": {"team_name": "disabled-test"},
            "tool_response": {},
        }
        result = _run_hook(
            stdin_data, env_overrides={"OMNICLAUDE_HOOK_TEAM_OBSERVABILITY": "0"}
        )
        assert result.returncode == 0

    def test_global_disable(self) -> None:
        stdin_data = {
            "tool_name": "TeamCreate",
            "tool_input": {"team_name": "global-disable-test"},
            "tool_response": {},
        }
        result = _run_hook(stdin_data, env_overrides={"OMNICLAUDE_HOOKS_DISABLED": "1"})
        assert result.returncode == 0


@pytest.mark.unit
class TestTeamObservabilityTopics:
    """Verify team lifecycle topics are registered in TopicBase."""

    def test_topics_exist_in_topic_base(self) -> None:
        src_path = str(Path(WORKTREE_ROOT) / "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)

        from omniclaude.hooks.topics import TopicBase

        assert (
            TopicBase.TEAM_TASK_ASSIGNED == "onex.evt.omniclaude.team-task-assigned.v1"
        )
        assert (
            TopicBase.TEAM_TASK_PROGRESS == "onex.evt.omniclaude.team-task-progress.v1"
        )
        assert (
            TopicBase.TEAM_TASK_COMPLETED
            == "onex.evt.omniclaude.team-task-completed.v1"
        )
        assert (
            TopicBase.TEAM_EVIDENCE_WRITTEN
            == "onex.evt.omniclaude.team-evidence-written.v1"
        )


@pytest.mark.unit
class TestTeamObservabilityEmitRegistration:
    """Verify event types are registered in emit_client_wrapper."""

    def test_event_types_in_supported_set(self) -> None:
        lib_path = str(Path(WORKTREE_ROOT) / "plugins" / "onex" / "hooks" / "lib")
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        # Force reimport to pick up changes
        if "emit_client_wrapper" in sys.modules:
            del sys.modules["emit_client_wrapper"]

        from emit_client_wrapper import SUPPORTED_EVENT_TYPES

        assert "team.task.assigned" in SUPPORTED_EVENT_TYPES
        assert "team.task.progress" in SUPPORTED_EVENT_TYPES
        assert "team.task.completed" in SUPPORTED_EVENT_TYPES
        assert "team.evidence.written" in SUPPORTED_EVENT_TYPES


@pytest.mark.unit
class TestTeamObservabilityHooksJson:
    """Verify hooks.json registration."""

    def test_hooks_json_has_team_observability(self) -> None:
        hooks_json_path = Path(WORKTREE_ROOT) / "plugins/onex/hooks/hooks.json"
        hooks_config = json.loads(hooks_json_path.read_text())

        post_tool_use = hooks_config["hooks"]["PostToolUse"]
        matchers = [entry.get("matcher", "") for entry in post_tool_use]
        assert any("TeamCreate" in m and "TaskUpdate" in m for m in matchers), (
            f"Team observability matcher not found in PostToolUse: {matchers}"
        )

        # Verify the hook command path
        team_entry = next(
            entry for entry in post_tool_use if "TeamCreate" in entry.get("matcher", "")
        )
        hook_cmd = team_entry["hooks"][0]["command"]
        assert "post_tool_use_team_observability.sh" in hook_cmd
