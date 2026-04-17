# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for permission_denied_logger.sh — PermissionDenied hook friction logger.

DoD evidence for OMN-8873: pipe mock JSON and assert YAML written with correct fields.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_SCRIPT = "plugins/onex/hooks/scripts/permission_denied_logger.sh"


def _run_hook(stdin_data: str, onex_state_dir: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = onex_state_dir
    # Unset so onex-paths.sh default doesn't override our temp dir
    env.pop("HOME", None)
    env["HOME"] = onex_state_dir
    return subprocess.run(
        ["bash", _SCRIPT],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        cwd=_REPO_ROOT,
        env=env,
    )


@pytest.mark.unit
def test_permission_denied_exits_zero_and_returns_empty_json() -> None:
    """Hook must exit 0 and emit {} — never block the tool call."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"tool_name": "Bash", "session_id": "sess-abc123"}),
            tmpdir,
        )
    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    assert json.loads(result.stdout) == {}


@pytest.mark.unit
def test_permission_denied_writes_friction_yaml() -> None:
    """Hook writes a friction YAML file in $ONEX_STATE_DIR/friction/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "session_id": "sess-test-001",
                    "agent_name": "worker-1",
                    "reason": "tool not in allowedTools",
                }
            ),
            tmpdir,
        )
        assert result.returncode == 0, f"Hook failed: {result.stderr}"

        friction_files = list(
            Path(tmpdir).glob("friction/*-permission-denied-bash-*.yaml")
        )
        assert len(friction_files) == 1, (
            f"Expected 1 friction file, got {len(friction_files)}. "
            f"Files: {list(Path(tmpdir).glob('friction/*'))}"
        )

        data = yaml.safe_load(friction_files[0].read_text())
        assert data["severity"] == "P2"
        assert data["category"] == "permission"
        assert "Bash" in data["title"]
        assert data["session_id"] == "sess-test-001"
        assert data["agent_name"] == "worker-1"
        assert "tool not in allowedTools" in data["root_cause"]


@pytest.mark.unit
def test_permission_denied_unknown_tool_name() -> None:
    """Hook handles missing tool_name gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"session_id": "sess-no-tool"}),
            tmpdir,
        )
        assert result.returncode == 0
        friction_files = list(
            Path(tmpdir).glob("friction/*-permission-denied-unknown-*.yaml")
        )
        assert len(friction_files) == 1
        data = yaml.safe_load(friction_files[0].read_text())
        assert data["severity"] == "P2"


@pytest.mark.unit
def test_permission_denied_no_retry_in_output() -> None:
    """Hook must NOT return {retry: true} — denial must be surfaced, not masked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"tool_name": "Edit", "session_id": "sess-retry-check"}),
            tmpdir,
        )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output.get("retry") is not True, "Hook must not set retry=true"


@pytest.mark.unit
def test_permission_denied_no_onex_state_dir_exits_zero_and_writes_no_file() -> None:
    """Hook exits 0 and emits {} when ONEX_STATE_DIR is unset.

    Per repo contract, ONEX_STATE_DIR must be set; unset is an infra failure.
    The hook must degrade gracefully (fail-open) without writing any friction file,
    even if onex-paths.sh would auto-default to $HOME/.onex_state.
    We set HOME to a temp dir to verify no file is created there.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env.pop("ONEX_STATE_DIR", None)
        env["HOME"] = tmpdir
        result = subprocess.run(
            ["bash", _SCRIPT],
            input=json.dumps({"tool_name": "Bash", "session_id": "sess-no-state"}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=_REPO_ROOT,
            env=env,
        )
        assert result.returncode == 0
        assert json.loads(result.stdout) == {}
        # No friction file must be written to the fallback HOME dir
        written = list(Path(tmpdir).rglob("*.yaml"))
        assert written == [], (
            f"Hook must not write fallback state when ONEX_STATE_DIR is unset, "
            f"but found: {written}"
        )
