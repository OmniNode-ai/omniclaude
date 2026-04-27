# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for post_tool_use_auto_hostile_review.sh disable behavior [OMN-10111]."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

# tests/unit/hooks/scripts/ -> 4 levels up
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "post_tool_use_auto_hostile_review.sh"
)


def _run(
    stdin_payload: Mapping[str, object], env: Mapping[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        input=json.dumps(dict(stdin_payload)),
        capture_output=True,
        text=True,
        env=dict(env),
        check=False,
    )


def _pr_create_payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {
            "command": "gh pr create --title 'foo' --body 'bar'",
        },
        "tool_response": {
            "stdout": "https://github.com/OmniNode-ai/omniclaude/pull/9999\n",
        },
    }


def _env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = str(tmp_path)
    env["HOME"] = str(tmp_path)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    env.pop("OMNICLAUDE_HOOKS_DISABLED", None)
    env.pop("OMNICLAUDE_HOOK_AUTO_HOSTILE_REVIEW", None)
    return env


@pytest.mark.unit
def test_lead_session_emits_gate_advisory(tmp_path: Path) -> None:
    """Without a sub-agent marker, the disabled hook emits no advisory."""
    session_id = f"lead-{uuid4()}"
    env = _env(tmp_path)
    proc = _run(_pr_create_payload(session_id), env)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    advisory = data.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert advisory == ""
    assert "hostile_reviewer disabled per OMN-10111" in proc.stderr


@pytest.mark.unit
def test_subagent_marker_emits_gate_only_advisory(tmp_path: Path) -> None:
    """With a sub-agent marker, the disabled hook still emits no advisory."""
    session_id = f"subagent-{uuid4()}"
    env = _env(tmp_path)
    # Write the sub-agent marker that subagent-start.sh would produce.
    marker_dir = tmp_path / "hooks" / "subagent-sessions"
    marker_dir.mkdir(parents=True, exist_ok=True)
    (marker_dir / f"{session_id}.marker").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "parent_session_id": "parent",
                "timestamp": "2026-04-19T00:00:00Z",
            }
        )
    )

    proc = _run(_pr_create_payload(session_id), env)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    advisory = data.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert advisory == ""
    assert "hostile_reviewer disabled per OMN-10111" in proc.stderr


@pytest.mark.unit
def test_non_pr_create_bash_passes_through_unchanged(tmp_path: Path) -> None:
    """A non-PR Bash command produces no advisory regardless of marker presence."""
    session_id = f"lead-{uuid4()}"
    env = _env(tmp_path)
    payload = {
        "session_id": session_id,
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
        "tool_response": {"stdout": ""},
    }
    proc = _run(payload, env)
    assert proc.returncode == 0, proc.stderr
    assert "hostile_reviewer" not in proc.stdout
