# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Sub-agent exemption + kill-switch end-to-end shell tests. [OMN-9140]

These tests exercise the real shell scripts
(`post-tool-delegation-counter.sh`, `subagent-start.sh`,
`post-skill-delegation-enforcer.sh`) with synthetic Claude Code stdin and
assert zero hard-block.

The tests run the scripts directly via bash — no Claude Code process needed.
That keeps them runnable in CI. A real Task() spawn would feed the same JSON
shape to the same scripts; failures here map 1:1 to failures in production.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"

COUNTER_SCRIPT = SCRIPTS_DIR / "post-tool-delegation-counter.sh"
SUBAGENT_START_SCRIPT = SCRIPTS_DIR / "subagent-start.sh"
SKILL_ENFORCER_SCRIPT = SCRIPTS_DIR / "post-skill-delegation-enforcer.sh"


def _env_with(tmp_path: Path, **overrides: str) -> dict[str, str]:
    """Build a subprocess env with ONEX_STATE_DIR pointed at tmp_path."""
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = str(tmp_path)
    # Fake HOME so the file-marker kill-switch is controlled per test.
    env["HOME"] = str(tmp_path)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    # Ensure the kill-switch is OFF unless the test sets it.
    env.pop("OMNICLAUDE_HOOKS_DISABLE", None)
    env.update(overrides)
    return env


def _run(
    script: Path, stdin_json: dict[str, object], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(stdin_json),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.unit
def test_subagent_marker_exempts_counter(tmp_path: Path) -> None:
    """SubagentStart writes a marker; 20 tool calls on that session never block."""
    session_id = f"subagent-{uuid4()}"
    parent_id = f"parent-{uuid4()}"
    env = _env_with(tmp_path)

    # SubagentStart writes the marker
    result = _run(
        SUBAGENT_START_SCRIPT,
        {
            "session_id": session_id,
            "parent_session_id": parent_id,
            "agent_name": "test-worker",
            "team_name": "test-team",
        },
        env,
    )
    assert result.returncode == 0, result.stderr
    marker = tmp_path / "hooks" / "subagent-sessions" / f"{session_id}.marker"
    assert marker.exists(), "SubagentStart did not write marker"

    # 20 tool calls through the counter — all should pass.
    for i in range(20):
        counter = _run(
            COUNTER_SCRIPT,
            {
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {"file_path": f"/tmp/example-{i}.txt"},
            },
            env,
        )
        assert counter.returncode == 0, (
            f"Sub-agent blocked at call #{i}: rc={counter.returncode} "
            f"stderr={counter.stderr} stdout={counter.stdout}"
        )


@pytest.mark.unit
def test_killswitch_env_var_short_circuits(tmp_path: Path) -> None:
    """OMNICLAUDE_HOOKS_DISABLE=1 bypasses the counter for a non-sub-agent session."""
    env = _env_with(tmp_path, OMNICLAUDE_HOOKS_DISABLE="1")
    session_id = f"root-{uuid4()}"
    for i in range(20):
        result = _run(
            COUNTER_SCRIPT,
            {
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {"file_path": f"/tmp/x-{i}.txt"},
            },
            env,
        )
        assert result.returncode == 0, (
            f"Kill-switch failed at call #{i}: rc={result.returncode}"
        )


@pytest.mark.unit
def test_killswitch_file_marker_short_circuits(tmp_path: Path) -> None:
    """~/.claude/omniclaude-hooks-disabled file marker bypasses the counter."""
    env = _env_with(tmp_path)
    (tmp_path / ".claude" / "omniclaude-hooks-disabled").touch()
    session_id = f"root-{uuid4()}"
    for i in range(20):
        result = _run(
            COUNTER_SCRIPT,
            {
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {"file_path": f"/tmp/x-{i}.txt"},
            },
            env,
        )
        assert result.returncode == 0, (
            f"File-marker kill-switch failed at call #{i}: rc={result.returncode}"
        )


@pytest.mark.unit
def test_skill_enforcer_killswitch(tmp_path: Path) -> None:
    """post-skill-delegation-enforcer.sh also honors the kill-switch."""
    env = _env_with(tmp_path, OMNICLAUDE_HOOKS_DISABLE="1")
    session_id = f"root-{uuid4()}"
    result = _run(
        SKILL_ENFORCER_SCRIPT,
        {
            "session_id": session_id,
            "tool_name": "Skill",
            "tool_input": {"skill": "demo-skill"},
        },
        env,
    )
    assert result.returncode == 0
    # Kill-switch path drains stdin silently — no additionalContext injected.
    assert "DELEGATION ENFORCER" not in result.stdout
