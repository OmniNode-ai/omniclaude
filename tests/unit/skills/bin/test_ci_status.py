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

from _lib.ci_status import (  # noqa: E402
    AUXILIARY_WORKFLOW_NAMES,
    REQUIRED_WORKFLOW_NAMES,
    _is_required_workflow,
    _run,
)


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

    @patch("_lib.ci_status.run_gh")
    def test_auxiliary_workflows_excluded(self, mock_run: MagicMock) -> None:
        """Auxiliary workflows (Release, Nightly) must be filtered out (OMN-6812)."""
        runs = [
            {
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
            {
                "name": "Release",
                "status": "completed",
                "conclusion": "failure",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
            {
                "name": "Nightly Tests",
                "status": "completed",
                "conclusion": "failure",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
        ]
        mock_run.return_value = _mock_gh_result(runs)
        status, result, msg = _run("x/y", "r1", {"pr": None})

        # Only the CI workflow should be counted
        assert status.value == "OK"
        assert result.summary["total"] == 1
        assert result.summary["passing"] == 1
        assert result.summary["failing"] == 0
        assert result.summary["all_green"] is True
        # Auxiliary skipped count recorded in inputs
        assert result.inputs["auxiliary_skipped"] == 2

    @patch("_lib.ci_status.run_gh")
    def test_only_auxiliary_workflows_returns_no_checks(
        self, mock_run: MagicMock
    ) -> None:
        """If only auxiliary workflows exist, result should be 'No CI checks found'."""
        runs = [
            {
                "name": "Release",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
            {
                "name": "Plugin Pin Cascade",
                "status": "completed",
                "conclusion": "success",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:01:00Z",
                "headBranch": "main",
            },
        ]
        mock_run.return_value = _mock_gh_result(runs)
        status, result, msg = _run("x/y", "r1", {"pr": None})

        assert status.value == "WARN"
        assert result.summary["total"] == 0
        assert "No CI checks found" in msg

    @patch("_lib.ci_status.run_gh")
    def test_ci_yml_name_matches(self, mock_run: MagicMock) -> None:
        """The 'ci.yml' workflow name should also be accepted."""
        runs = [
            {
                "name": "ci.yml",
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


@pytest.mark.unit
class TestWorkflowFilter:
    """Tests for the workflow name filter (OMN-6812)."""

    def test_ci_is_required(self) -> None:
        assert _is_required_workflow("CI") is True

    def test_ci_yml_is_required(self) -> None:
        assert _is_required_workflow("ci.yml") is True

    def test_case_insensitive(self) -> None:
        assert _is_required_workflow("ci") is True
        assert _is_required_workflow("Ci.Yml") is True

    def test_release_is_not_required(self) -> None:
        assert _is_required_workflow("Release") is False

    def test_nightly_is_not_required(self) -> None:
        assert _is_required_workflow("Nightly Tests") is False

    def test_plugin_pin_cascade_is_not_required(self) -> None:
        assert _is_required_workflow("Plugin Pin Cascade") is False

    def test_empty_name_is_not_required(self) -> None:
        assert _is_required_workflow("") is False

    def test_required_workflow_names_has_expected_entries(self) -> None:
        assert "ci.yml" in REQUIRED_WORKFLOW_NAMES
        assert "CI" in REQUIRED_WORKFLOW_NAMES

    def test_auxiliary_names_documented(self) -> None:
        assert len(AUXILIARY_WORKFLOW_NAMES) > 0
        assert "Release" in AUXILIARY_WORKFLOW_NAMES
