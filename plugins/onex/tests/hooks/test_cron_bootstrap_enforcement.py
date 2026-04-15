# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for cron bootstrap enforcement hooks (OMN-8845).

Verifies:
- post_tool_use_cron_action_guard.sh writes the bootstrap flag when all 3 mandatory
  crons have been seen in the session.
- stop_session_bootstrap_guard.sh exits 2 when flag is absent, exits 0 when present.
- user_prompt_bootstrap_injector.sh injects a warning when flag is absent, exits 0 when
  present without injecting.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPTS_DIR = Path(__file__).parent.parent.parent / "hooks" / "scripts"
PLUGIN_ROOT = Path(__file__).parent.parent.parent

# The 3 mandatory cron prompts (substring matches used by the guard)
OVERSEER_PROMPT = "Overseer tick: (1) Nudge/relaunch stalled agents."
MERGE_SWEEP_PROMPT = "Merge sweep: list all open PRs, enable auto-merge on clean ones"
HEALTH_CHECK_PROMPT = "Dispatch haiku health worker: SSH .201 container state"


def _make_cron_stdin(schedule: str, prompt: str) -> str:
    """Build a fake CronCreate PostToolUse stdin payload."""
    return json.dumps(
        {
            "tool_name": "CronCreate",
            "tool_input": {"schedule": schedule, "prompt": prompt},
            "tool_response": {"cronId": "fake-id"},
        }
    )


class TestPostToolUseCronActionGuard:
    """Tests for post_tool_use_cron_action_guard.sh bootstrap flag writing."""

    def test_flag_absent_after_single_cron(self, tmp_path: Path) -> None:
        """Flag must NOT be written when only 1 of 3 crons have been seen."""
        flag_path = tmp_path / "session" / "cron_bootstrap.flag"
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        stdin = _make_cron_stdin("*/15 * * * *", OVERSEER_PROMPT)
        result = subprocess.run(
            [str(SCRIPTS_DIR / "post_tool_use_cron_action_guard.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        assert not flag_path.exists(), "Flag must not be written after only 1 cron"

    def test_flag_written_after_all_three_crons(self, tmp_path: Path) -> None:
        """Flag MUST be written after all 3 mandatory crons are seen."""
        flag_path = tmp_path / "session" / "cron_bootstrap.flag"
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        crons = [
            ("*/15 * * * *", OVERSEER_PROMPT),
            ("23 * * * *", MERGE_SWEEP_PROMPT),
            ("3 * * * *", HEALTH_CHECK_PROMPT),
        ]
        for schedule, prompt in crons:
            stdin = _make_cron_stdin(schedule, prompt)
            result = subprocess.run(
                [str(SCRIPTS_DIR / "post_tool_use_cron_action_guard.sh")],
                input=stdin,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            assert result.returncode == 0

        assert flag_path.exists(), "Flag must be written after all 3 mandatory crons"
        content = flag_path.read_text()
        assert content.strip(), "Flag file must not be empty"


class TestStopSessionBootstrapGuard:
    """Tests for stop_session_bootstrap_guard.sh exit codes."""

    def test_exits_2_when_flag_absent(self, tmp_path: Path) -> None:
        """Must exit 2 and emit BLOCKED message when bootstrap flag is absent."""
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        stdin = json.dumps(
            {"sessionId": "test-session", "completion_status": "complete"}
        )
        result = subprocess.run(
            [str(SCRIPTS_DIR / "stop_session_bootstrap_guard.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 2, (
            f"Expected exit 2 when flag absent, got {result.returncode}. "
            f"stderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "BLOCKED" in combined, "Must emit BLOCKED message when flag absent"
        assert "bootstrap" in combined.lower(), "Must mention bootstrap in message"

    def test_exits_0_when_flag_present(self, tmp_path: Path) -> None:
        """Must exit 0 when bootstrap flag is present."""
        flag_path = tmp_path / "session" / "cron_bootstrap.flag"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text("2026-04-15T00:00:00Z")
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        stdin = json.dumps(
            {"sessionId": "test-session", "completion_status": "complete"}
        )
        result = subprocess.run(
            [str(SCRIPTS_DIR / "stop_session_bootstrap_guard.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 when flag present, got {result.returncode}. "
            f"stderr: {result.stderr}"
        )


class TestUserPromptBootstrapInjector:
    """Tests for user_prompt_bootstrap_injector.sh context injection."""

    def test_injects_warning_when_flag_absent(self, tmp_path: Path) -> None:
        """Must inject MANDATORY warning when bootstrap flag is absent."""
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        stdin = json.dumps({"sessionId": "test-session", "prompt": "do some work"})
        result = subprocess.run(
            [str(SCRIPTS_DIR / "user_prompt_bootstrap_injector.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0, (
            f"UserPromptSubmit hook must never block (exit 0 always). "
            f"Got {result.returncode}. stderr: {result.stderr}"
        )
        # Output must be JSON with hookSpecificOutput.additionalContext
        output = json.loads(result.stdout)
        additional = output.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "MANDATORY" in additional, (
            "Must inject MANDATORY warning in additionalContext"
        )
        assert "bootstrap" in additional.lower(), "Must mention bootstrap"

    def test_no_injection_when_flag_present(self, tmp_path: Path) -> None:
        """Must not inject warning when bootstrap flag is already present."""
        flag_path = tmp_path / "session" / "cron_bootstrap.flag"
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text("2026-04-15T00:00:00Z")
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path),
            "CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT),
        }
        stdin = json.dumps({"sessionId": "test-session", "prompt": "do some work"})
        result = subprocess.run(
            [str(SCRIPTS_DIR / "user_prompt_bootstrap_injector.sh")],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode == 0
        # Either empty output or JSON without MANDATORY injection
        if result.stdout.strip():
            output = json.loads(result.stdout)
            additional = output.get("hookSpecificOutput", {}).get(
                "additionalContext", ""
            )
            assert "MANDATORY" not in additional, (
                "Must NOT inject MANDATORY when flag present"
            )
