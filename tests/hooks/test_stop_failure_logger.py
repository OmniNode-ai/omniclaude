# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for stop_failure_logger.sh — StopFailure hook friction logger.

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
_SCRIPT = "plugins/onex/hooks/scripts/stop_failure_logger.sh"


def _run_hook(stdin_data: str, onex_state_dir: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = onex_state_dir
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
def test_stop_failure_exits_zero_and_returns_empty_json() -> None:
    """Hook must exit 0 and emit {} — never block Claude Code."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"session_id": "sess-abc123", "reason": "API error: 529"}),
            tmpdir,
        )
    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    assert json.loads(result.stdout) == {}


@pytest.mark.unit
def test_stop_failure_writes_friction_yaml() -> None:
    """Hook writes a P1 friction YAML in $ONEX_STATE_DIR/friction/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps(
                {
                    "session_id": "sess-test-002",
                    "agent_name": "pipeline-worker",
                    "reason": "API error: 529 overloaded",
                    "turn_count": 17,
                }
            ),
            tmpdir,
        )
        assert result.returncode == 0, f"Hook failed: {result.stderr}"

        friction_files = list(
            Path(tmpdir).glob("friction/*-stop-failure-pipeline-worker-*.yaml")
        )
        assert len(friction_files) == 1, (
            f"Expected 1 friction file, got {len(friction_files)}. "
            f"Files: {list(Path(tmpdir).glob('friction/*'))}"
        )

        data = yaml.safe_load(friction_files[0].read_text())
        assert data["severity"] == "P1", "API errors are P1 — more serious than denials"
        assert data["category"] == "api_error"
        assert "pipeline-worker" in data["title"]
        assert data["session_id"] == "sess-test-002"
        assert data["agent_name"] == "pipeline-worker"
        assert "529" in data["root_cause"]
        assert data["turn_count"] == 17


@pytest.mark.unit
def test_stop_failure_unknown_agent() -> None:
    """Hook handles missing agent_name gracefully — uses 'unknown'."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"session_id": "sess-no-agent", "reason": "timeout"}),
            tmpdir,
        )
        assert result.returncode == 0
        friction_files = list(
            Path(tmpdir).glob("friction/*-stop-failure-unknown-*.yaml")
        )
        assert len(friction_files) == 1
        data = yaml.safe_load(friction_files[0].read_text())
        assert data["severity"] == "P1"
        assert "timeout" in data["root_cause"]


@pytest.mark.unit
def test_stop_failure_null_turn_count() -> None:
    """Hook writes friction YAML correctly when turn_count is absent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(
            json.dumps({"session_id": "sess-no-turns", "agent_name": "worker-x"}),
            tmpdir,
        )
        assert result.returncode == 0
        friction_files = list(
            Path(tmpdir).glob("friction/*-stop-failure-worker-x-*.yaml")
        )
        assert len(friction_files) == 1
        data = yaml.safe_load(friction_files[0].read_text())
        assert data["turn_count"] is None


@pytest.mark.unit
def test_stop_failure_no_onex_state_dir_exits_zero() -> None:
    """Hook exits 0 when ONEX_STATE_DIR is unset (infra failure tolerance).

    onex-paths.sh defaults ONEX_STATE_DIR to $HOME/.onex_state, so we provide
    a real tmpdir for HOME so the hook can cd there successfully.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env.pop("ONEX_STATE_DIR", None)
        env["HOME"] = tmpdir
        result = subprocess.run(
            ["bash", _SCRIPT],
            input=json.dumps({"session_id": "sess-no-state", "reason": "API error"}),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=_REPO_ROOT,
            env=env,
        )
    assert result.returncode == 0
    assert json.loads(result.stdout) == {}
