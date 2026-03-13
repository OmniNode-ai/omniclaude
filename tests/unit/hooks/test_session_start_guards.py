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
