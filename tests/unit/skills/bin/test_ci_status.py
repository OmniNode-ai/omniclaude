# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/ci_status.py -- CI status backend."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.ci_status import _run  # noqa: E402


def _mock_gh_result(data: list[dict]) -> MagicMock:
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = json.dumps(data)
    mock.returncode = 0
    return mock


@pytest.mark.unit
class TestCiStatusPr:
    """Tests for CI status with a specific PR."""

    @patch("_lib.ci_status.run_gh")
    def test_all_passing(self, mock_run: MagicMock) -> None:
        checks = [
            {"name": "test", "state": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "state": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        mock_run.return_value = _mock_gh_result(checks)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "OK"
        assert result.summary["all_green"] is True
        assert result.summary["passing"] == 2
        assert result.summary["failing"] == 0
        assert "All 2 checks passing" in msg

    @patch("_lib.ci_status.run_gh")
    def test_some_failing(self, mock_run: MagicMock) -> None:
        checks = [
            {"name": "test", "state": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "lint", "state": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "security", "state": "COMPLETED", "conclusion": "ERROR"},
        ]
        mock_run.return_value = _mock_gh_result(checks)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "WARN"
        assert result.summary["failing"] == 2
        assert "lint" in result.summary["failing_names"]
        assert "security" in result.summary["failing_names"]

    @patch("_lib.ci_status.run_gh")
    def test_pending_checks(self, mock_run: MagicMock) -> None:
        checks = [
            {"name": "test", "state": "IN_PROGRESS", "conclusion": ""},
            {"name": "lint", "state": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        mock_run.return_value = _mock_gh_result(checks)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "OK"
        assert result.summary["pending"] == 1
        assert result.summary["all_green"] is False

    @patch("_lib.ci_status.run_gh")
    def test_no_checks(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_gh_result([])
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "WARN"
        assert "No CI checks found" in msg


@pytest.mark.unit
class TestCiStatusBranch:
    """Tests for CI status on default branch (no --pr)."""

    @patch("_lib.ci_status.run_gh")
    def test_default_branch_runs(self, mock_run: MagicMock) -> None:
        runs = [
            {
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
        ]
        mock_run.return_value = _mock_gh_result(runs)
        status, result, msg = _run("x/y", "r1", {"pr": None})

        assert status.value == "OK"
        assert result.summary["passing"] == 1
