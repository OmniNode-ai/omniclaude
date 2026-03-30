# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for SubagentStart hook — ONEX conventions injection."""

import json
import subprocess
from pathlib import Path

import pytest

# Resolve repo root from test file location (tests/hooks/test_*.py -> repo root)
_REPO_ROOT = str(Path(__file__).resolve().parents[2])


@pytest.mark.unit
def test_subagent_start_injects_onex_conventions() -> None:
    """SubagentStart hook injects compact ONEX conventions bundle."""
    stdin_data = json.dumps(
        {
            "sessionId": "test-session",
            "agentName": "worker-1",
            "teamName": "test-team",
            "parentSessionId": "parent-session",
        }
    )
    result = subprocess.run(
        ["bash", "plugins/onex/hooks/scripts/subagent-start.sh"],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    output = json.loads(result.stdout)
    additional_context = output.get("hookSpecificOutput", {}).get(
        "additionalContext", ""
    )

    # Structural checks
    assert additional_context, "additionalContext must be non-empty"
    assert additional_context.startswith("## ONEX Conventions"), (
        "Must begin with section header"
    )

    # Count bullet lines (convention items)
    lines = [
        line
        for line in additional_context.strip().split("\n")
        if line.strip().startswith("-")
    ]
    assert len(lines) >= 8, f"Expected at least 8 convention bullets, got {len(lines)}"

    # Critical invariant checks
    assert "Node types: Effect/Compute/Reducer/Orchestrator" in additional_context
    assert "Model prefix" in additional_context
    assert "contract" in additional_context.lower()
    assert "omni_worktrees" in additional_context  # worktree root enforcement
    assert "--no-verify" in additional_context  # no-verify prohibition


@pytest.mark.unit
def test_subagent_start_returns_valid_json() -> None:
    """SubagentStart hook returns well-formed JSON with hookSpecificOutput."""
    stdin_data = json.dumps(
        {
            "sessionId": "test-session-2",
            "agentName": "worker-2",
        }
    )
    result = subprocess.run(
        ["bash", "plugins/onex/hooks/scripts/subagent-start.sh"],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, f"Hook failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert "hookSpecificOutput" in output
    assert "additionalContext" in output["hookSpecificOutput"]


@pytest.mark.unit
def test_subagent_start_safety_conventions() -> None:
    """SubagentStart hook includes safety-critical conventions."""
    stdin_data = json.dumps({"sessionId": "test-safety"})
    result = subprocess.run(
        ["bash", "plugins/onex/hooks/scripts/subagent-start.sh"],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    ctx = output["hookSpecificOutput"]["additionalContext"]

    # Safety invariants that must be present
    assert "never use --no-verify" in ctx.lower()
    assert "never disable safety" in ctx.lower() or "Never disable safety" in ctx
    assert "~/.claude/" in ctx  # prohibition on writing to ~/.claude/
    assert "two-strike" in ctx.lower() or "Two-strike" in ctx
