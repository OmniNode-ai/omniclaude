# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/pr_scan.py -- PR scanning backend."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.pr_scan import _run  # noqa: E402


def _mock_gh_result(prs: list[dict]) -> MagicMock:
    """Create a mock CompletedProcess with JSON PR data."""
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = json.dumps(prs)
    mock.returncode = 0
    return mock


@pytest.mark.unit
class TestPrScan:
    """Tests for PR scan backend."""

    @patch("_lib.pr_scan.run_gh")
    def test_empty_repo(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_gh_result([])
        status, result, msg = _run("OmniNode-ai/test", "run-1", {})

        assert status.value == "OK"
        assert result.summary["total_open"] == 0
        assert "0 open PRs" in msg

    @patch("_lib.pr_scan.run_gh")
    def test_mixed_prs(self, mock_run: MagicMock) -> None:
        prs = [
            {
                "number": 1,
                "title": "Feature A",
                "headRefName": "feature-a",
                "author": {"login": "dev1"},
                "isDraft": False,
                "reviewDecision": "APPROVED",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS", "name": "test"},
                ],
            },
            {
                "number": 2,
                "title": "Draft B",
                "headRefName": "draft-b",
                "author": {"login": "dev2"},
                "isDraft": True,
                "reviewDecision": None,
                "mergeable": "UNKNOWN",
                "statusCheckRollup": [],
            },
            {
                "number": 3,
                "title": "Failing C",
                "headRefName": "failing-c",
                "author": {"login": "dev3"},
                "isDraft": False,
                "reviewDecision": "CHANGES_REQUESTED",
                "mergeable": "CONFLICTING",
                "statusCheckRollup": [
                    {"conclusion": "FAILURE", "name": "lint"},
                ],
            },
        ]
        mock_run.return_value = _mock_gh_result(prs)
        status, result, msg = _run("OmniNode-ai/test", "run-2", {})

        assert result.summary["total_open"] == 3
        assert result.summary["drafts"] == 1
        assert result.summary["approved"] == 1
        assert result.summary["changes_requested"] == 1
        assert result.summary["ci_failing"] == 1
        assert result.summary["ci_passing"] == 1
        assert status.value == "WARN"  # CI failing

    @patch("_lib.pr_scan.run_gh")
    def test_all_passing(self, mock_run: MagicMock) -> None:
        prs = [
            {
                "number": 1,
                "title": "Good PR",
                "headRefName": "good",
                "author": {"login": "dev"},
                "isDraft": False,
                "reviewDecision": "APPROVED",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [
                    {"conclusion": "SUCCESS", "name": "test"},
                ],
            },
        ]
        mock_run.return_value = _mock_gh_result(prs)
        status, result, msg = _run("OmniNode-ai/test", "run-3", {})

        assert status.value == "OK"
        assert result.summary["ci_failing"] == 0

    @patch("_lib.pr_scan.run_gh")
    def test_meta_fields(self, mock_run: MagicMock) -> None:
        mock_run.return_value = _mock_gh_result([])
        _, result, _ = _run("OmniNode-ai/test", "run-meta", {})

        assert result.meta.script == "pr_scan"
        assert result.meta.run_id == "run-meta"
        assert result.meta.repo == "OmniNode-ai/test"

    @patch("_lib.pr_scan.run_gh")
    def test_parsed_structure(self, mock_run: MagicMock) -> None:
        """Parsed output should not contain raw gh tokens."""
        prs = [
            {
                "number": 1,
                "title": "Test",
                "headRefName": "test",
                "author": {"login": "dev"},
                "isDraft": False,
                "reviewDecision": "APPROVED",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            },
        ]
        mock_run.return_value = _mock_gh_result(prs)
        _, result, _ = _run("OmniNode-ai/test", "run-parsed", {})

        parsed_json = json.dumps(result.parsed)
        assert "Authorization" not in parsed_json
        assert (
            "token" not in parsed_json.lower() or "token" in "statusCheckRollup".lower()
        )
