# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""AGENT_ID path-traversal sanitization tests for
``post_tool_use_subagent_tool_log.sh`` (OMN-9084).

Rejects any AGENT_ID that is not a slug matching ``^[a-zA-Z0-9_-]{1,64}$``
before interpolation into ``$ONEX_STATE_DIR/dispatches/<agent>/``. This
blocks ``..`` and path separators without breaking normal slugged dispatch
ids. Rejection emits a friction record and exits 0 (passthrough).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


HOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "post_tool_use_subagent_tool_log.sh"
)


def _run_hook(
    agent_id: str, state_dir: Path, *, via_env: bool = True
) -> subprocess.CompletedProcess[str]:
    event = {
        "agent_id": agent_id if not via_env else "",
        "tool_name": "Read",
        "tool_response": {"decision": "allow", "duration_ms": 1, "error": None},
    }
    env = {
        "ONEX_STATE_DIR": str(state_dir),
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(state_dir),
    }
    if via_env:
        env["ONEX_AGENT_ID"] = agent_id
    return subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_valid_slug_creates_dispatch_dir(tmp_path: Path) -> None:
    result = _run_hook("worker-1", tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatches" / "worker-1").is_dir()
    assert not (tmp_path / "friction" / "agent_id_reject").exists()


def test_dotdot_agent_id_rejected(tmp_path: Path) -> None:
    """The literal string '..' must be rejected; no dir outside dispatches/."""
    result = _run_hook("..", tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "dispatches" / "..").exists()
    assert (tmp_path / "friction" / "agent_id_reject").is_dir()
    friction_files = list((tmp_path / "friction" / "agent_id_reject").iterdir())
    assert len(friction_files) == 1


def test_slash_agent_id_rejected(tmp_path: Path) -> None:
    """AGENT_ID containing '/' must be rejected before mkdir -p."""
    result = _run_hook("evil/../../etc", tmp_path)
    assert result.returncode == 0, result.stderr
    # No directory traversal artefact anywhere under tmp_path except friction.
    assert not (tmp_path / "etc").exists()
    assert (tmp_path / "friction" / "agent_id_reject").is_dir()


def test_dot_agent_id_rejected(tmp_path: Path) -> None:
    """Single '.' is rejected — dots are not in the slug charset."""
    result = _run_hook("agent.1", tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "dispatches" / "agent.1").exists()
    assert (tmp_path / "friction" / "agent_id_reject").is_dir()


def test_overlong_agent_id_rejected(tmp_path: Path) -> None:
    """AGENT_ID longer than 64 chars is rejected."""
    long_id = "a" * 65
    result = _run_hook(long_id, tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "dispatches" / long_id).exists()
    assert (tmp_path / "friction" / "agent_id_reject").is_dir()


def test_max_length_agent_id_accepted(tmp_path: Path) -> None:
    """Exactly 64-char slug AGENT_ID is accepted."""
    exact_id = "a" * 64
    result = _run_hook(exact_id, tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "dispatches" / exact_id).is_dir()


def test_empty_agent_id_short_circuits(tmp_path: Path) -> None:
    """Empty AGENT_ID exits 0 without mkdir or friction (existing behavior)."""
    result = _run_hook("", tmp_path)
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "dispatches").exists()
    assert not (tmp_path / "friction" / "agent_id_reject").exists()
