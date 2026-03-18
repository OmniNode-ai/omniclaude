# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for OMNICLAUDE_MODE resolution."""

import os
import subprocess
from pathlib import Path

import pytest

# Path to mode.sh relative to repo root
MODE_SH = Path(__file__).parents[3] / "plugins" / "onex" / "lib" / "mode.sh"


@pytest.mark.unit
def test_explicit_lite_mode():
    env = {**os.environ, "OMNICLAUDE_MODE": "lite"}
    result = subprocess.run(
        ["bash", "-c", f"source {MODE_SH} && omniclaude_mode"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stdout.strip() == "lite"


@pytest.mark.unit
def test_explicit_full_mode():
    env = {**os.environ, "OMNICLAUDE_MODE": "full"}
    result = subprocess.run(
        ["bash", "-c", f"source {MODE_SH} && omniclaude_mode"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stdout.strip() == "full"


@pytest.mark.unit
def test_auto_detect_external_project(tmp_path):
    """When cwd is NOT under omni_home or omni_worktrees, auto-detect lite."""
    env = {k: v for k, v in os.environ.items() if k != "OMNICLAUDE_MODE"}
    # Also ensure no omnibase_core on PATH to force lite
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        ["bash", "-c", f"source {MODE_SH} && omniclaude_mode"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.stdout.strip() == "lite"


@pytest.mark.unit
def test_explicit_mode_overrides_autodetect(tmp_path):
    """Explicit OMNICLAUDE_MODE=full should win even in non-OmniNode directory."""
    env = {**os.environ, "OMNICLAUDE_MODE": "full"}
    result = subprocess.run(
        ["bash", "-c", f"source {MODE_SH} && omniclaude_mode"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )
    assert result.stdout.strip() == "full"
