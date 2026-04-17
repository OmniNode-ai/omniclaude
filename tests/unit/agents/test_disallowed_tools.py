# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for agent disallowedTools schema field and enforcement (OMN-8842)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

AGENTS_DIR = Path(__file__).parents[3] / "plugins" / "onex" / "agents" / "configs"
HOOKS_LIB = Path(__file__).parents[3] / "plugins" / "onex" / "hooks" / "lib"


# ---------------------------------------------------------------------------
# Schema field tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_disallowed_tools_field_defaults_to_empty_list() -> None:
    """Agent YAML without disallowedTools loads with empty list default."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        agent_yaml = {
            "schema_version": "1.0.0",
            "agent_type": "test_agent",
            "agent_identity": {"name": "agent-test", "description": "test"},
        }
        result = agent_tool_gate.get_disallowed_tools(agent_yaml)
        assert result == []
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_disallowed_tools_field_loads_from_yaml() -> None:
    """Agent YAML with disallowedTools list is accessible after load."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        agent_yaml = {
            "schema_version": "1.0.0",
            "agent_type": "background_worker",
            "agent_identity": {"name": "agent-background-worker", "description": "bg"},
            "disallowedTools": ["CronCreate", "CronDelete", "CronList"],
        }
        result = agent_tool_gate.get_disallowed_tools(agent_yaml)
        assert result == ["CronCreate", "CronDelete", "CronList"]
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_disallowed_tools_agent_router_includes_field() -> None:
    """_build_registry_from_configs preserves disallowedTools in registry entry."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_router

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_file = Path(tmpdir) / "agent-background-worker.yaml"
            agent_data = {
                "schema_version": "1.0.0",
                "mode": "full",
                "agent_type": "background_worker",
                "agent_identity": {
                    "name": "agent-background-worker",
                    "description": "Background worker",
                },
                "activation_patterns": {
                    "explicit_triggers": ["background task"],
                },
                "disallowedTools": ["CronCreate", "CronDelete", "CronList"],
            }
            agent_file.write_text(yaml.dump(agent_data))

            registry = agent_router._build_registry_from_configs(Path(tmpdir))

        agent_entry = registry["agents"]["agent-background-worker"]
        assert "disallowed_tools" in agent_entry
        assert agent_entry["disallowed_tools"] == [
            "CronCreate",
            "CronDelete",
            "CronList",
        ]
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_router", None)


# ---------------------------------------------------------------------------
# Enforcement tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_enforcement_blocks_disallowed_tool() -> None:
    """When active agent disallows a tool, hook returns exit 2 block."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        hook_input = json.dumps(
            {
                "tool_name": "CronCreate",
                "tool_input": {"schedule": "*/15 * * * *", "prompt": "tick"},
                "session_id": "test-session",
            }
        )

        agent_yaml = {
            "agent_identity": {"name": "agent-background-worker"},
            "disallowedTools": ["CronCreate", "CronDelete", "CronList"],
        }

        result = agent_tool_gate.check_tool_allowed(
            tool_name="CronCreate",
            agent_data=agent_yaml,
        )
        assert result.blocked is True
        assert "agent-background-worker" in result.reason
        assert "CronCreate" in result.reason
        assert "disallowedTools" in result.reason
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_enforcement_allows_non_disallowed_tool() -> None:
    """When tool is not in disallowedTools, check passes."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        agent_yaml = {
            "agent_identity": {"name": "agent-background-worker"},
            "disallowedTools": ["CronCreate", "CronDelete", "CronList"],
        }

        result = agent_tool_gate.check_tool_allowed(
            tool_name="Bash",
            agent_data=agent_yaml,
        )
        assert result.blocked is False
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_enforcement_allows_all_tools_when_no_disallowed_list() -> None:
    """When disallowedTools is absent, all tools are allowed."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        agent_yaml = {
            "agent_identity": {"name": "agent-pr-review"},
        }

        result = agent_tool_gate.check_tool_allowed(
            tool_name="CronCreate",
            agent_data=agent_yaml,
        )
        assert result.blocked is False
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_main_blocks_via_stdin_when_agent_disallows_tool() -> None:
    """main() reads stdin, resolves agent, exits 2 with block message."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        hook_json = json.dumps(
            {
                "tool_name": "CronCreate",
                "tool_input": {},
                "session_id": "s1",
            }
        )

        agent_yaml = {
            "agent_identity": {"name": "agent-background-worker"},
            "disallowedTools": ["CronCreate", "CronDelete", "CronList"],
        }

        output_buf: list[str] = []
        exit_code_captured: list[int] = []

        def fake_exit(code: int) -> None:
            exit_code_captured.append(code)
            raise SystemExit(code)

        with (
            mock.patch.object(
                agent_tool_gate, "_load_active_agent_yaml", return_value=agent_yaml
            ),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: output_buf.append(str(a[0])),
            ),
            mock.patch("sys.exit", side_effect=fake_exit),
        ):
            with pytest.raises(SystemExit) as exc_info:
                agent_tool_gate.main(stdin=io.StringIO(hook_json))

        assert exc_info.value.code == 2
        assert output_buf, "Expected block message printed to stdout"
        block_msg = output_buf[0]
        parsed = json.loads(block_msg)
        assert "reason" in parsed or "hookSpecificOutput" in parsed
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)


@pytest.mark.unit
def test_main_passes_through_when_no_active_agent() -> None:
    """main() exits 0 and echoes input when no active agent is found."""
    sys.path.insert(0, str(HOOKS_LIB))
    try:
        import agent_tool_gate

        hook_json = json.dumps(
            {
                "tool_name": "CronCreate",
                "tool_input": {},
                "session_id": "s1",
            }
        )

        output_buf: list[str] = []

        with (
            mock.patch.object(
                agent_tool_gate, "_load_active_agent_yaml", return_value=None
            ),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: output_buf.append(str(a[0])),
            ),
        ):
            agent_tool_gate.main(stdin=io.StringIO(hook_json))

        assert output_buf
        # Should echo the original input (pass-through)
        assert "CronCreate" in output_buf[0]
    finally:
        sys.path.pop(0)
        sys.modules.pop("agent_tool_gate", None)
