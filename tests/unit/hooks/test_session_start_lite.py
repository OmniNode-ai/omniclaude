# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for SessionStart lite-mode graceful degradation."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("plugins/onex/hooks/scripts/session-start.sh")
STDIN_PAYLOAD = '{"session_id":"test-lite-123","cwd":"/tmp/external-project","hook_event_name":"SessionStart"}'


def _lite_env() -> dict[str, str]:
    """Build a subprocess env with OMNICLAUDE_MODE=lite."""
    env = os.environ.copy()
    env["OMNICLAUDE_MODE"] = "lite"
    return env


@pytest.mark.unit
def test_session_start_exits_zero_in_lite_mode() -> None:
    """SessionStart must exit 0 in lite mode without starting the daemon."""
    assert SCRIPT.exists(), f"Script not found at {SCRIPT}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
        timeout=10,
        env=_lite_env(),
    )
    assert result.returncode == 0, (
        f"SessionStart failed in lite mode (exit {result.returncode}).\n"
        f"stderr: {result.stderr}"
    )


@pytest.mark.unit
def test_session_start_outputs_valid_json_in_lite_mode() -> None:
    """SessionStart must emit valid JSON with hookSpecificOutput in lite mode."""
    assert SCRIPT.exists(), f"Script not found at {SCRIPT}"

    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
        timeout=10,
        env=_lite_env(),
    )
    assert result.returncode == 0, f"Non-zero exit: {result.stderr}"

    output = json.loads(result.stdout.strip())
    assert "hookSpecificOutput" in output, (
        f"Missing hookSpecificOutput in lite-mode JSON.\nstdout: {result.stdout}"
    )
    assert (
        "lite" in output["hookSpecificOutput"].get("additionalContext", "").lower()
    ), "Expected 'lite' mentioned in additionalContext"


@pytest.mark.unit
def test_session_start_exports_omniclaude_mode() -> None:
    """OMNICLAUDE_MODE=lite must be preserved (not overwritten) by session-start."""
    assert SCRIPT.exists(), f"Script not found at {SCRIPT}"

    # The script exits before doing anything heavy, so OMNICLAUDE_MODE stays lite.
    # We verify indirectly: if the output is the lite JSON, mode was respected.
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input=STDIN_PAYLOAD,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
        timeout=10,
        env=_lite_env(),
    )
    assert result.returncode == 0, f"Non-zero exit: {result.stderr}"
    output = json.loads(result.stdout.strip())
    assert "lite" in output["hookSpecificOutput"]["additionalContext"]
