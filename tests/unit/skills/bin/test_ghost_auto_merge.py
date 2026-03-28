# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for _bin/_lib/ghost_auto_merge.py -- ghost auto-merge detection and recovery."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BIN_DIR = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills" / "_bin"
sys.path.insert(0, str(_BIN_DIR))

from _lib.ghost_auto_merge import (  # noqa: E402
    GHOST_THRESHOLD_MINUTES,
    EnumGhostRecoveryAction,
    EnumGhostRecoveryResult,
    ModelGhostAutoMergeStatus,
    detect_ghost_auto_merge,
    recover_ghost_auto_merge,
    scan_for_ghost_auto_merges,
)


def _mock_gh_result(data: dict | list) -> MagicMock:
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = json.dumps(data)
    mock.returncode = 0
    return mock


NOW = datetime(2026, 3, 27, 12, 0, 0, tzinfo=UTC)
FORTY_MIN_AGO = (NOW - timedelta(minutes=40)).isoformat()
TEN_MIN_AGO = (NOW - timedelta(minutes=10)).isoformat()


@pytest.mark.unit
class TestDetectGhostAutoMerge:
    """Tests for ghost auto-merge detection."""

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_no_auto_merge_enabled(self, mock_run: MagicMock) -> None:
        """PR without auto-merge is not ghost."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": None,
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)

        assert status.is_ghost is False
        assert status.auto_merge_enabled is False
        assert status.recovery_result == EnumGhostRecoveryResult.NOT_GHOST

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_auto_merge_not_clean(self, mock_run: MagicMock) -> None:
        """PR with auto-merge but checks not passing is not ghost."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": {"enabledAt": FORTY_MIN_AGO},
                "mergeStateStatus": "BLOCKED",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)

        assert status.is_ghost is False
        assert status.auto_merge_enabled is True
        assert status.checks_passing is False

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_auto_merge_clean_but_recent(self, mock_run: MagicMock) -> None:
        """PR with auto-merge + CLEAN but within threshold is not ghost."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": {"enabledAt": TEN_MIN_AGO},
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)

        assert status.is_ghost is False
        assert status.auto_merge_enabled is True
        assert status.checks_passing is True
        assert status.minutes_stuck < GHOST_THRESHOLD_MINUTES

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_ghost_detected(self, mock_run: MagicMock) -> None:
        """PR with auto-merge + CLEAN + past threshold is ghost."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": {"enabledAt": FORTY_MIN_AGO},
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)

        assert status.is_ghost is True
        assert status.auto_merge_enabled is True
        assert status.checks_passing is True
        assert status.minutes_stuck > GHOST_THRESHOLD_MINUTES
        assert status.auto_merge_enabled_at == FORTY_MIN_AGO

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_custom_threshold(self, mock_run: MagicMock) -> None:
        """Custom threshold correctly changes ghost detection."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": {"enabledAt": TEN_MIN_AGO},
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        # With default 30 min threshold, 10 min is not ghost
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)
        assert status.is_ghost is False

        # With 5 min threshold, 10 min IS ghost
        status = detect_ghost_auto_merge("org/repo", 42, threshold_minutes=5, now=NOW)
        assert status.is_ghost is True

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_missing_enabled_at_defaults_to_not_ghost(
        self, mock_run: MagicMock
    ) -> None:
        """If enabledAt is missing, minutes_stuck stays 0 so PR is not ghost."""
        mock_run.return_value = _mock_gh_result(
            {
                "autoMergeRequest": {},
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
                "statusCheckRollup": [],
            }
        )
        status = detect_ghost_auto_merge("org/repo", 42, now=NOW)

        # No enabledAt means minutes_stuck stays 0 → not ghost by default
        assert status.is_ghost is False


@pytest.mark.unit
class TestRecoverGhostAutoMerge:
    """Tests for ghost auto-merge recovery."""

    @patch("_lib.ghost_auto_merge.time.sleep")
    @patch("_lib.ghost_auto_merge.detect_ghost_auto_merge")
    @patch("_lib.ghost_auto_merge._enable_auto_merge")
    @patch("_lib.ghost_auto_merge._disable_auto_merge")
    def test_toggle_recovery_succeeds(
        self,
        mock_disable: MagicMock,
        mock_enable: MagicMock,
        mock_detect: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """Toggle off/on resolves ghost state (auto-merge consumed by queue)."""
        ghost_status = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            auto_merge_enabled_at=FORTY_MIN_AGO,
            minutes_stuck=40.0,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )

        # After toggle, auto-merge is no longer enabled (PR entered merge queue)
        mock_detect.return_value = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=False,
            auto_merge_enabled=False,
            checks_passing=True,
            recovery_result=EnumGhostRecoveryResult.NOT_GHOST,
        )

        result = recover_ghost_auto_merge("org/repo", 42, ghost_status, toggle_delay=0)

        assert result.recovery_action == EnumGhostRecoveryAction.TOGGLE
        assert result.recovery_result == EnumGhostRecoveryResult.RECOVERED
        assert result.is_ghost is False
        mock_disable.assert_called_once_with("org/repo", 42)
        mock_enable.assert_called_once_with("org/repo", 42)

    @patch("_lib.ghost_auto_merge.time.sleep")
    @patch("_lib.ghost_auto_merge.detect_ghost_auto_merge")
    @patch("_lib.ghost_auto_merge._direct_merge")
    @patch("_lib.ghost_auto_merge._enable_auto_merge")
    @patch("_lib.ghost_auto_merge._disable_auto_merge")
    def test_toggle_fails_direct_merge_succeeds(
        self,
        mock_disable: MagicMock,
        mock_enable: MagicMock,
        mock_direct: MagicMock,
        mock_detect: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """If toggle doesn't resolve, fall back to direct merge."""
        ghost_status = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            auto_merge_enabled_at=FORTY_MIN_AGO,
            minutes_stuck=40.0,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )

        # After toggle, still ghost (auto-merge still enabled)
        mock_detect.return_value = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )

        result = recover_ghost_auto_merge("org/repo", 42, ghost_status, toggle_delay=0)

        assert result.recovery_action == EnumGhostRecoveryAction.DIRECT_MERGE
        assert result.recovery_result == EnumGhostRecoveryResult.RECOVERED
        mock_direct.assert_called_once_with("org/repo", 42)

    @patch("_lib.ghost_auto_merge.time.sleep")
    @patch("_lib.ghost_auto_merge.detect_ghost_auto_merge")
    @patch("_lib.ghost_auto_merge._direct_merge")
    @patch("_lib.ghost_auto_merge._enable_auto_merge")
    @patch("_lib.ghost_auto_merge._disable_auto_merge")
    def test_both_recovery_attempts_fail(
        self,
        mock_disable: MagicMock,
        mock_enable: MagicMock,
        mock_direct: MagicMock,
        mock_detect: MagicMock,
        mock_sleep: MagicMock,
    ) -> None:
        """If both toggle and direct merge fail, return FAILED status."""
        ghost_status = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            auto_merge_enabled_at=FORTY_MIN_AGO,
            minutes_stuck=40.0,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )

        # Toggle seems to work but PR is still in ghost state
        mock_detect.return_value = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )

        # Direct merge fails
        mock_direct.side_effect = subprocess.CalledProcessError(
            1, "gh", stderr="API error"
        )

        result = recover_ghost_auto_merge("org/repo", 42, ghost_status, toggle_delay=0)

        assert result.recovery_action == EnumGhostRecoveryAction.DIRECT_MERGE
        assert result.recovery_result == EnumGhostRecoveryResult.FAILED
        assert result.is_ghost is True
        assert result.error is not None

    def test_not_ghost_skips_recovery(self) -> None:
        """Non-ghost PRs skip recovery entirely."""
        status = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=42,
            is_ghost=False,
            auto_merge_enabled=True,
            checks_passing=True,
            recovery_result=EnumGhostRecoveryResult.NOT_GHOST,
        )

        result = recover_ghost_auto_merge("org/repo", 42, status)
        assert result.recovery_result == EnumGhostRecoveryResult.NOT_GHOST
        assert result is status  # returned unchanged


@pytest.mark.unit
class TestScanForGhostAutoMerges:
    """Tests for batch scanning."""

    @patch("_lib.ghost_auto_merge.detect_ghost_auto_merge")
    @patch("_lib.ghost_auto_merge.run_gh")
    def test_finds_ghost_prs(self, mock_run: MagicMock, mock_detect: MagicMock) -> None:
        """Scan correctly identifies ghost PRs from a list."""
        prs = [
            {
                "number": 10,
                "autoMergeRequest": {"enabledAt": FORTY_MIN_AGO},
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            {
                "number": 11,
                "autoMergeRequest": None,
                "mergeStateStatus": "CLEAN",
                "mergeable": "MERGEABLE",
            },
            {
                "number": 12,
                "autoMergeRequest": {"enabledAt": TEN_MIN_AGO},
                "mergeStateStatus": "BLOCKED",
                "mergeable": "MERGEABLE",
            },
        ]
        mock_run.return_value = _mock_gh_result(prs)

        # Only PR #10 is ghost
        ghost_status = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=10,
            is_ghost=True,
            auto_merge_enabled=True,
            checks_passing=True,
            minutes_stuck=40.0,
            recovery_result=EnumGhostRecoveryResult.SKIPPED,
        )
        not_ghost = ModelGhostAutoMergeStatus(
            repo="org/repo",
            pr_number=12,
            is_ghost=False,
            auto_merge_enabled=True,
            checks_passing=False,
            recovery_result=EnumGhostRecoveryResult.NOT_GHOST,
        )
        mock_detect.side_effect = [ghost_status, not_ghost]

        results = scan_for_ghost_auto_merges("org/repo", now=NOW)

        assert len(results) == 1
        assert results[0].pr_number == 10
        assert results[0].is_ghost is True
        # PR #11 (no auto-merge) should not have been checked
        assert mock_detect.call_count == 2  # only #10 and #12 have autoMergeRequest

    @patch("_lib.ghost_auto_merge.run_gh")
    def test_no_open_prs(self, mock_run: MagicMock) -> None:
        """Empty PR list returns empty ghost list."""
        mock_run.return_value = _mock_gh_result([])
        results = scan_for_ghost_auto_merges("org/repo", now=NOW)
        assert results == []


@pytest.mark.unit
class TestModelGhostAutoMergeStatus:
    """Tests for the status model."""

    def test_frozen(self) -> None:
        status = ModelGhostAutoMergeStatus(repo="org/repo", pr_number=1)
        with pytest.raises(Exception):
            status.is_ghost = True  # type: ignore[misc]

    def test_defaults(self) -> None:
        status = ModelGhostAutoMergeStatus(repo="org/repo", pr_number=1)
        assert status.is_ghost is False
        assert status.auto_merge_enabled is False
        assert status.checks_passing is False
        assert status.recovery_action == EnumGhostRecoveryAction.NONE
        assert status.recovery_result == EnumGhostRecoveryResult.NOT_GHOST
        assert status.error is None
