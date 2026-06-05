# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for OMN-12696 Stop/SubagentStop skip-token surface guard."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
HOOK_SCRIPT = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "skip_token_surface_guard.sh"
)


def _run_guard(
    payload: dict[str, object],
    *,
    hook_event: str,
    project_dir: Path,
    state_dir: Path,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PLUGIN_PYTHON_BIN"] = sys.executable
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT / "plugins" / "onex")
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["ONEX_STATE_DIR"] = str(state_dir)
    env["OMNICLAUDE_SKIP_TOKEN_HOOK_EVENT"] = hook_event
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        check=False,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )


@pytest.mark.unit
def test_subagent_stop_blocks_skip_token_in_final_message(tmp_path: Path) -> None:
    result = _run_guard(
        {"final_message": "Use [skip-receipt-gate: docs only] here."},
        hook_event="SubagentStop",
        project_dir=tmp_path / "repo",
        state_dir=tmp_path / "state",
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    output = payload["hookSpecificOutput"]
    assert output["hookEventName"] == "SubagentStop"
    assert output["decision"] == "block"
    assert "final assistant message" in output["additionalContext"]


@pytest.mark.unit
def test_stop_allows_skip_token_with_approval_receipt(tmp_path: Path) -> None:
    result = _run_guard(
        {
            "final_message": (
                "Approved exception [skip-receipt-gate: test].\n"
                "# skip-token-allowed: USER-APPROVAL-OMN-12696"
            )
        },
        hook_event="Stop",
        project_dir=tmp_path / "repo",
        state_dir=tmp_path / "state",
    )

    assert result.returncode == 0
    assert result.stdout == ""


@pytest.mark.unit
def test_stop_blocks_skip_token_in_session_evidence(tmp_path: Path) -> None:
    project_dir = tmp_path / "repo"
    evidence_dir = project_dir / ".onex_state" / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "session.json").write_text(
        '{"claim": "[skip-receipt-gate: no receipt]"}',
        encoding="utf-8",
    )

    result = _run_guard(
        {"final_message": "clean"},
        hook_event="Stop",
        project_dir=project_dir,
        state_dir=tmp_path / "state",
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "session evidence" in payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.unit
def test_hooks_json_registers_guard_for_stop_and_subagent_stop() -> None:
    hooks_json = REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())

    for event_name in ("Stop", "SubagentStop"):
        commands = [
            hook["command"]
            for group in data["hooks"][event_name]
            for hook in group.get("hooks", [])
        ]
        assert any("skip_token_surface_guard.sh" in command for command in commands)
