#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for epic pre-flight and post-action validation gate scripts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

# Resolve script paths relative to the plugin root
_PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "onex"
_PREFLIGHT_SCRIPT = _PLUGIN_ROOT / "hooks" / "scripts" / "epic_preflight_gate.sh"
_POSTACTION_SCRIPT = _PLUGIN_ROOT / "hooks" / "scripts" / "epic_postaction_gate.sh"


@pytest.mark.unit
class TestEpicPreflightGate:
    """Tests for epic_preflight_gate.sh."""

    def test_preflight_exits_zero_for_valid_ticket(self) -> None:
        """Preflight gate exits 0 when ticket maps to exactly one repo."""
        result = subprocess.run(
            ["bash", str(_PREFLIGHT_SCRIPT)],
            env={
                **os.environ,
                "TICKET_ID": "OMN-1234",
                "TICKET_REPO": "omniclaude",
                "EPIC_ID": "OMN-6521",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_preflight_exits_nonzero_for_missing_repo(self) -> None:
        """Preflight gate exits 1 when ticket has no repo assignment."""
        result = subprocess.run(
            ["bash", str(_PREFLIGHT_SCRIPT)],
            env={
                **os.environ,
                "TICKET_ID": "OMN-1234",
                "TICKET_REPO": "",
                "EPIC_ID": "OMN-6521",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "FAIL" in result.stderr


@pytest.mark.unit
class TestEpicPostactionGate:
    """Tests for epic_postaction_gate.sh."""

    def test_postaction_dry_run_exits_zero(self) -> None:
        """Post-action gate exits 0 in dry-run mode."""
        result = subprocess.run(
            ["bash", str(_POSTACTION_SCRIPT)],
            env={
                **os.environ,
                "WORKTREE_PATH": "/tmp",
                "TICKET_ID": "OMN-1234",
                "DRY_RUN": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "DRY_RUN" in result.stdout

    def test_postaction_writes_gate_result_json(self, tmp_path: Path) -> None:
        """Post-action gate writes structured JSON result."""
        result_file = tmp_path / "gate-result.json"
        subprocess.run(
            ["bash", str(_POSTACTION_SCRIPT)],
            env={
                **os.environ,
                "WORKTREE_PATH": "/tmp",
                "TICKET_ID": "OMN-1234",
                "DRY_RUN": "1",
                "GATE_RESULT_FILE": str(result_file),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result_file.exists()
        data = json.loads(result_file.read_text())
        assert data["ticket_id"] == "OMN-1234"
        assert data["passed"] == 1
