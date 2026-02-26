# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/pr_merge_readiness.py -- merge readiness backend."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.pr_merge_readiness import _run  # noqa: E402


def _mock_gh_result(data: dict) -> MagicMock:
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = json.dumps(data)
    mock.returncode = 0
    return mock


@pytest.mark.unit
class TestPrMergeReadiness:
    """Tests for PR merge readiness backend."""

    def test_no_pr_number(self) -> None:
        status, result, msg = _run("x/y", "r1", {"pr": None})
        assert status.value == "FAIL"
        assert "--pr is required" in msg

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_ready_to_merge(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "title": "Good PR",
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS", "name": "test"},
                {"conclusion": "SUCCESS", "name": "lint"},
            ],
            "reviews": [{"state": "APPROVED", "author": {"login": "reviewer"}}],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "OK"
        assert result.summary["ready_to_merge"] is True
        assert result.summary["blocker_count"] == 0
        assert "ready to merge" in msg

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_draft_pr(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "state": "OPEN",
            "isDraft": True,
            "mergeable": "MERGEABLE",
            "reviewDecision": "",
            "statusCheckRollup": [],
            "reviews": [],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert status.value == "WARN"
        assert result.summary["ready_to_merge"] is False
        assert "draft" in result.summary["blockers"][0].lower()

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_ci_failing(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS", "name": "test"},
                {"conclusion": "FAILURE", "name": "lint"},
            ],
            "reviews": [{"state": "APPROVED"}],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert result.summary["ready_to_merge"] is False
        assert any("CI failing" in b for b in result.summary["blockers"])

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_changes_requested(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviewDecision": "CHANGES_REQUESTED",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS", "name": "test"},
            ],
            "reviews": [{"state": "CHANGES_REQUESTED"}],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert result.summary["ready_to_merge"] is False
        assert any("Changes requested" in b for b in result.summary["blockers"])

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_merge_conflicts(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "CONFLICTING",
            "reviewDecision": "APPROVED",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS", "name": "test"},
            ],
            "reviews": [{"state": "APPROVED"}],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert result.summary["ready_to_merge"] is False
        assert any("conflict" in b.lower() for b in result.summary["blockers"])

    @patch("_lib.pr_merge_readiness.run_gh")
    def test_no_reviews(self, mock_run: MagicMock) -> None:
        pr_data = {
            "number": 42,
            "state": "OPEN",
            "isDraft": False,
            "mergeable": "MERGEABLE",
            "reviewDecision": "",
            "statusCheckRollup": [
                {"conclusion": "SUCCESS", "name": "test"},
            ],
            "reviews": [],
            "comments": [],
        }
        mock_run.return_value = _mock_gh_result(pr_data)
        status, result, msg = _run("x/y", "r1", {"pr": 42})

        assert result.summary["ready_to_merge"] is False
        assert any("No approved" in b for b in result.summary["blockers"])
