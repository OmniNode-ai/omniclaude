# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for session-start.sh environment guards."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.unit
def test_inmemory_guard_blocks_session_start() -> None:
    """session-start.sh --guard-check-only must exit non-zero when ONEX_EVENT_BUS_TYPE=inmemory."""
    script = Path("plugins/onex/hooks/scripts/session-start.sh")
    assert script.exists(), f"Script not found at {script}"

    env = os.environ.copy()
    env["ONEX_EVENT_BUS_TYPE"] = "inmemory"

    result = subprocess.run(
        ["bash", str(script), "--guard-check-only"],
        env=env,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
    )
    assert result.returncode != 0, (
        f"Expected non-zero exit when ONEX_EVENT_BUS_TYPE=inmemory, got 0.\n"
        f"stderr: {result.stderr}"
    )
    assert "inmemory" in result.stderr.lower() or "FORBIDDEN" in result.stderr, (
        f"Expected 'inmemory' or 'FORBIDDEN' in stderr.\nstderr: {result.stderr}"
    )


@pytest.mark.unit
def test_inmemory_guard_catches_project_env(tmp_path: Path) -> None:
    """Guard must catch ONEX_EVENT_BUS_TYPE=inmemory set in the project .env file.

    Regression test for CodeRabbit review on PR #628: the inmemory guard
    previously ran before the project .env was sourced, so project-level
    settings slipped through undetected.
    """
    script = Path("plugins/onex/hooks/scripts/session-start.sh").resolve()
    assert script.exists(), f"Script not found at {script}"

    # Create a fake project root with .env containing the forbidden value.
    # CLAUDE_PLUGIN_ROOT is set so that PLUGIN_ROOT/../.. resolves to tmp_path.
    plugin_dir = tmp_path / "plugins" / "onex"
    plugin_dir.mkdir(parents=True)
    env_file = tmp_path / ".env"
    env_file.write_text("ONEX_EVENT_BUS_TYPE=inmemory\n")

    env = os.environ.copy()
    # Ensure the variable is NOT in the parent shell -- only in the .env file.
    env.pop("ONEX_EVENT_BUS_TYPE", None)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_dir)

    result = subprocess.run(
        ["bash", str(script), "--guard-check-only"],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert result.returncode != 0, (
        f"Expected non-zero exit when .env sets ONEX_EVENT_BUS_TYPE=inmemory, got 0.\n"
        f"stderr: {result.stderr}"
    )
    assert "inmemory" in result.stderr.lower(), (
        f"Expected 'inmemory' in stderr.\nstderr: {result.stderr}"
    )


@pytest.mark.unit
def test_guard_check_only_passes_without_inmemory() -> None:
    """session-start.sh --guard-check-only must exit 0 when ONEX_EVENT_BUS_TYPE is not set."""
    script = Path("plugins/onex/hooks/scripts/session-start.sh")
    env = os.environ.copy()
    env.pop("ONEX_EVENT_BUS_TYPE", None)

    result = subprocess.run(
        ["bash", str(script), "--guard-check-only"],
        env=env,
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
        check=False,
    )
    assert result.returncode == 0, (
        f"Expected exit 0 when ONEX_EVENT_BUS_TYPE is unset.\nstderr: {result.stderr}"
    )
