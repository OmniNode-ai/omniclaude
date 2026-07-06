# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for _bin/_lib/armed_not_enqueued.py (OMN-13031).

Tests the armed-not-enqueued detector: PRs where autoMergeRequest != null AND
mergeStateStatus == CLEAN AND no ADDED_TO_MERGE_QUEUE_EVENT newer than the
arming timestamp, sustained >30 minutes.
"""

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

import pydantic  # noqa: E402
from _lib.armed_not_enqueued import (  # noqa: E402
    ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES,
    QUEUE_REPOS,
    EnumArmedNotEnqueuedStatus,
    ModelArmedNotEnqueuedFinding,
    ModelArmedNotEnqueuedScanResult,
    detect_armed_not_enqueued,
    render_summary,
    scan_all_queue_repos,
    scan_repo,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
FORTY_MIN_AGO = (NOW - timedelta(minutes=40)).isoformat()
TEN_MIN_AGO = (NOW - timedelta(minutes=10)).isoformat()
THIRTY_ONE_MIN_AGO = (NOW - timedelta(minutes=31)).isoformat()


def _mock_gh(data: dict | list) -> MagicMock:
    """Build a mock CompletedProcess with JSON stdout."""
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.stdout = json.dumps(data)
    mock.returncode = 0
    return mock


def _make_pr(
    number: int = 42,
    title: str = "Test PR",
    head_ref: str = "feature/test",
    auto_merge: dict | None = None,
    merge_state: str = "CLEAN",
) -> dict:
    return {
        "number": number,
        "title": title,
        "headRefName": head_ref,
        "autoMergeRequest": auto_merge,
        "mergeStateStatus": merge_state,
    }


def _make_queue_event(created_at: str) -> dict:
    return {"event": "added_to_merge_queue", "created_at": created_at}


# ---------------------------------------------------------------------------
# detect_armed_not_enqueued — single-PR classification
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetectArmedNotEnqueued:
    """Single-PR classification tests."""

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_not_armed_pr_is_not_armed(self, mock_events: MagicMock) -> None:
        """PR with no autoMergeRequest is classified NOT_ARMED."""
        pr = _make_pr(auto_merge=None)
        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.NOT_ARMED
        assert finding.flagged is False
        mock_events.assert_not_called()

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_armed_checks_pending_not_flagged(self, mock_events: MagicMock) -> None:
        """Armed PR with non-CLEAN mergeStateStatus is ARMED_CHECKS_PENDING."""
        pr = _make_pr(auto_merge={"enabledAt": FORTY_MIN_AGO}, merge_state="BLOCKED")
        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.ARMED_CHECKS_PENDING
        assert finding.flagged is False
        # No need to probe timeline when checks aren't clean
        mock_events.assert_not_called()

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_armed_clean_no_queue_event_over_threshold_is_flagged(
        self, mock_events: MagicMock
    ) -> None:
        """Armed + CLEAN + no queue event + >30 min = ARMED_NOT_ENQUEUED + flagged."""
        mock_events.return_value = []
        pr = _make_pr(auto_merge={"enabledAt": FORTY_MIN_AGO})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED
        assert finding.flagged is True
        assert (
            finding.minutes_armed_without_queue > ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES
        )
        assert finding.queue_event_count == 0

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_armed_clean_no_queue_event_under_threshold_not_flagged(
        self, mock_events: MagicMock
    ) -> None:
        """Armed + CLEAN + no queue event + <30 min = ARMED_NOT_ENQUEUED but NOT flagged."""
        mock_events.return_value = []
        pr = _make_pr(auto_merge={"enabledAt": TEN_MIN_AGO})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED
        assert finding.flagged is False
        assert (
            finding.minutes_armed_without_queue < ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES
        )

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_armed_clean_queue_event_after_arming_is_clean(
        self, mock_events: MagicMock
    ) -> None:
        """Armed + CLEAN + queue event after arming = CLEAN (correctly enqueued)."""
        queue_event_ts = (NOW - timedelta(minutes=5)).isoformat()
        mock_events.return_value = [_make_queue_event(queue_event_ts)]
        pr = _make_pr(auto_merge={"enabledAt": FORTY_MIN_AGO})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.CLEAN
        assert finding.flagged is False
        assert finding.queue_event_count == 1
        assert finding.last_queue_event_at == queue_event_ts

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_queue_event_before_arming_still_flagged(
        self, mock_events: MagicMock
    ) -> None:
        """Queue event BEFORE the current arming does not count — PR is still not enqueued."""
        # Armed 10 min ago, but the only queue event was 40 min ago (before arming)
        old_queue_event = (NOW - timedelta(minutes=40)).isoformat()
        armed_ts = TEN_MIN_AGO  # 10 min ago
        mock_events.return_value = [_make_queue_event(old_queue_event)]
        pr = _make_pr(auto_merge={"enabledAt": armed_ts})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        # Queue event predates arming — PR is not enqueued for this arming session
        assert finding.status == EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED
        assert finding.flagged is False  # Only 10 min, under threshold

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_missing_enabled_at_not_flagged(self, mock_events: MagicMock) -> None:
        """Missing enabledAt: cannot determine elapsed time, so PR is not flagged.

        Unknown elapsed time is not the same as overdue — we do not fabricate
        a duration when the arming timestamp is absent or unparsable.
        """
        mock_events.return_value = []
        pr = _make_pr(auto_merge={})  # No enabledAt

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        # Unknown timestamp = not flagged (unknown ≠ overdue)
        assert finding.status == EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED
        assert finding.flagged is False
        assert finding.minutes_armed_without_queue == 0.0

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_custom_threshold(self, mock_events: MagicMock) -> None:
        """Custom threshold changes the flagging boundary."""
        mock_events.return_value = []
        pr = _make_pr(auto_merge={"enabledAt": TEN_MIN_AGO})

        # Default 30 min: not flagged
        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)
        assert finding.flagged is False

        # 5 min threshold: flagged
        finding = detect_armed_not_enqueued(
            "org/repo", pr, threshold_minutes=5, now=NOW
        )
        assert finding.flagged is True

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_exactly_at_threshold_not_flagged(self, mock_events: MagicMock) -> None:
        """PR armed exactly at the threshold boundary is NOT flagged (> not >=)."""
        armed_ts = (
            NOW - timedelta(minutes=ARMED_NOT_ENQUEUED_THRESHOLD_MINUTES)
        ).isoformat()
        mock_events.return_value = []
        pr = _make_pr(auto_merge={"enabledAt": armed_ts})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        # Exactly at threshold: not flagged (condition is > threshold)
        assert finding.flagged is False

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_multiple_queue_events_picks_latest(self, mock_events: MagicMock) -> None:
        """When multiple queue events exist, the most recent is used."""
        early_ts = (NOW - timedelta(minutes=20)).isoformat()
        late_ts = (NOW - timedelta(minutes=2)).isoformat()
        mock_events.return_value = [
            _make_queue_event(early_ts),
            _make_queue_event(late_ts),
        ]
        pr = _make_pr(auto_merge={"enabledAt": FORTY_MIN_AGO})

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.status == EnumArmedNotEnqueuedStatus.CLEAN
        assert finding.last_queue_event_at == late_ts
        assert finding.queue_event_count == 2

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    def test_finding_fields_populated(self, mock_events: MagicMock) -> None:
        """All finding fields are populated correctly on a flagged PR."""
        mock_events.return_value = []
        pr = _make_pr(
            number=99,
            title="My important PR",
            head_ref="feature/something",
            auto_merge={"enabledAt": FORTY_MIN_AGO},
        )

        finding = detect_armed_not_enqueued("org/repo", pr, now=NOW)

        assert finding.repo == "org/repo"
        assert finding.pr_number == 99
        assert finding.pr_title == "My important PR"
        assert finding.head_ref == "feature/something"
        assert finding.armed_at == FORTY_MIN_AGO
        assert finding.merge_state_status == "CLEAN"


# ---------------------------------------------------------------------------
# scan_repo
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanRepo:
    """Tests for single-repo scanning."""

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    @patch("_lib.armed_not_enqueued._fetch_pr_list")
    def test_skips_unarmed_prs(
        self, mock_list: MagicMock, mock_events: MagicMock
    ) -> None:
        """PRs without autoMergeRequest are not returned in findings."""
        mock_list.return_value = [
            _make_pr(number=1, auto_merge=None),
            _make_pr(number=2, auto_merge=None),
        ]
        findings, errors = scan_repo("org/repo", now=NOW)

        assert findings == []
        assert errors == []
        mock_events.assert_not_called()

    @patch("_lib.armed_not_enqueued._fetch_queue_events")
    @patch("_lib.armed_not_enqueued._fetch_pr_list")
    def test_returns_findings_for_armed_prs(
        self, mock_list: MagicMock, mock_events: MagicMock
    ) -> None:
        """Armed PRs appear in findings regardless of status."""
        mock_list.return_value = [
            _make_pr(number=10, auto_merge={"enabledAt": FORTY_MIN_AGO}),
            _make_pr(number=11, auto_merge={"enabledAt": TEN_MIN_AGO}),
        ]
        mock_events.return_value = []

        findings, errors = scan_repo("org/repo", now=NOW)

        assert len(findings) == 2
        assert errors == []
        # PR 10: >30 min → flagged
        f10 = next(f for f in findings if f.pr_number == 10)
        assert f10.flagged is True
        # PR 11: <30 min → not flagged yet
        f11 = next(f for f in findings if f.pr_number == 11)
        assert f11.flagged is False

    @patch("_lib.armed_not_enqueued._fetch_pr_list")
    def test_fetch_error_returns_error_not_exception(
        self, mock_list: MagicMock
    ) -> None:
        """Fetch failure returns an error string, not a raised exception."""
        mock_list.side_effect = subprocess.CalledProcessError(1, "gh")

        findings, errors = scan_repo("org/repo", now=NOW)

        assert findings == []
        assert len(errors) == 1
        assert "org/repo" in errors[0]


# ---------------------------------------------------------------------------
# scan_all_queue_repos
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScanAllQueueRepos:
    """Tests for multi-repo scan aggregation."""

    @patch("_lib.armed_not_enqueued.scan_repo")
    def test_aggregates_findings_across_repos(self, mock_scan: MagicMock) -> None:
        """Findings from multiple repos are merged into a single result."""
        finding_a = ModelArmedNotEnqueuedFinding(
            repo="org/repo-a",
            pr_number=1,
            status=EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED,
            flagged=True,
            minutes_armed_without_queue=40.0,
        )
        finding_b = ModelArmedNotEnqueuedFinding(
            repo="org/repo-b",
            pr_number=2,
            status=EnumArmedNotEnqueuedStatus.ARMED_CHECKS_PENDING,
            flagged=False,
        )

        def _side_effect(repo: str, **_: object) -> tuple[list, list]:
            if repo == "org/repo-a":
                return [finding_a], []
            elif repo == "org/repo-b":
                return [finding_b], []
            return [], []

        mock_scan.side_effect = _side_effect

        result = scan_all_queue_repos(repos=("org/repo-a", "org/repo-b"), now=NOW)

        assert result.flagged_count == 1
        assert len(result.findings) == 2
        assert len(result.repos_scanned) == 2
        assert result.scan_errors == []

    @patch("_lib.armed_not_enqueued.scan_repo")
    def test_scan_errors_aggregated(self, mock_scan: MagicMock) -> None:
        """Scan errors from individual repos are collected into the result."""
        mock_scan.return_value = ([], ["org/repo: fetch failed — API error"])

        result = scan_all_queue_repos(repos=("org/repo",), now=NOW)

        assert len(result.scan_errors) == 1
        assert "fetch failed" in result.scan_errors[0]

    @patch("_lib.armed_not_enqueued.scan_repo")
    def test_default_repos_are_queue_repos(self, mock_scan: MagicMock) -> None:
        """Without explicit repos arg, all QUEUE_REPOS are scanned."""
        mock_scan.return_value = ([], [])

        result = scan_all_queue_repos(now=NOW)

        assert set(result.repos_scanned) == set(QUEUE_REPOS)
        assert mock_scan.call_count == len(QUEUE_REPOS)

    @patch("_lib.armed_not_enqueued.scan_repo")
    def test_flagged_count_correct(self, mock_scan: MagicMock) -> None:
        """flagged_count accurately reflects findings with flagged=True."""
        findings = [
            ModelArmedNotEnqueuedFinding(
                repo="org/r",
                pr_number=i,
                status=EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED,
                flagged=(i < 3),  # PRs 0,1,2 are flagged; 3,4 are not
                minutes_armed_without_queue=40.0 if i < 3 else 5.0,
            )
            for i in range(5)
        ]
        mock_scan.return_value = (findings, [])

        result = scan_all_queue_repos(repos=("org/r",), now=NOW)

        assert result.flagged_count == 3

    @patch("_lib.armed_not_enqueued.scan_repo")
    def test_result_is_frozen(self, mock_scan: MagicMock) -> None:
        """ModelArmedNotEnqueuedScanResult is immutable (frozen=True)."""
        mock_scan.return_value = ([], [])
        result = scan_all_queue_repos(repos=("org/r",), now=NOW)

        with pytest.raises(pydantic.ValidationError):
            result.flagged_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# render_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRenderSummary:
    """Tests for human-readable summary output."""

    def test_renders_flagged_section(self) -> None:
        finding = ModelArmedNotEnqueuedFinding(
            repo="OmniNode-ai/omniclaude",
            pr_number=123,
            pr_title="Fix something important",
            status=EnumArmedNotEnqueuedStatus.ARMED_NOT_ENQUEUED,
            armed_at=FORTY_MIN_AGO,
            flagged=True,
            minutes_armed_without_queue=40.0,
        )
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=["OmniNode-ai/omniclaude"],
            findings=[finding],
            flagged_count=1,
        )

        summary = render_summary(result)

        assert "FLAGGED" in summary
        assert "PR#123" in summary
        assert "Fix something important" in summary
        assert "40.0" in summary

    def test_renders_clean_state(self) -> None:
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=["OmniNode-ai/omniclaude"],
            findings=[],
            flagged_count=0,
        )

        summary = render_summary(result)

        assert "FLAGGED (0)" in summary
        assert "no armed-not-enqueued PRs" in summary

    def test_renders_checks_pending_section(self) -> None:
        finding = ModelArmedNotEnqueuedFinding(
            repo="org/r",
            pr_number=5,
            pr_title="Pending checks",
            status=EnumArmedNotEnqueuedStatus.ARMED_CHECKS_PENDING,
            merge_state_status="BLOCKED",
        )
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=["org/r"],
            findings=[finding],
            flagged_count=0,
        )

        summary = render_summary(result)

        assert "ARMED (checks pending)" in summary
        assert "BLOCKED" in summary

    def test_renders_correctly_enqueued_section(self) -> None:
        finding = ModelArmedNotEnqueuedFinding(
            repo="org/r",
            pr_number=7,
            pr_title="In queue",
            status=EnumArmedNotEnqueuedStatus.CLEAN,
            last_queue_event_at=TEN_MIN_AGO,
            queue_event_count=1,
        )
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=["org/r"],
            findings=[finding],
            flagged_count=0,
        )

        summary = render_summary(result)

        assert "CLEAN (correctly enqueued)" in summary

    def test_renders_scan_errors(self) -> None:
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=["org/r"],
            findings=[],
            flagged_count=0,
            scan_errors=["org/r: fetch failed — timeout"],
        )

        summary = render_summary(result)

        assert "SCAN ERRORS" in summary
        assert "fetch failed" in summary

    def test_total_line_always_present(self) -> None:
        result = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=[],
            findings=[],
            flagged_count=0,
        )
        summary = render_summary(result)
        assert "Total findings:" in summary
        assert "Flagged:" in summary


# ---------------------------------------------------------------------------
# Model invariants
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelInvariants:
    """Model struct invariants — frozen, extra=forbid."""

    def test_finding_frozen(self) -> None:
        f = ModelArmedNotEnqueuedFinding(
            repo="org/r",
            pr_number=1,
            status=EnumArmedNotEnqueuedStatus.NOT_ARMED,
        )
        with pytest.raises(pydantic.ValidationError):
            f.flagged = True  # type: ignore[misc]

    def test_scan_result_frozen(self) -> None:
        r = ModelArmedNotEnqueuedScanResult(
            scanned_at=NOW.isoformat(),
            repos_scanned=[],
            findings=[],
            flagged_count=0,
        )
        with pytest.raises(pydantic.ValidationError):
            r.flagged_count = 99  # type: ignore[misc]

    def test_finding_extra_forbid(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            ModelArmedNotEnqueuedFinding(
                repo="org/r",
                pr_number=1,
                status=EnumArmedNotEnqueuedStatus.NOT_ARMED,
                unexpected_field="oops",  # type: ignore[call-arg]
            )

    def test_queue_repos_constant_covers_all_queue_repos(self) -> None:
        """QUEUE_REPOS must include all documented queue repos.

        onex_change_control was removed 2026-07-06 (OMN-14077) when its merge
        queue (ruleset 16846914) was disabled — it now merges via the direct
        squash path and is not subject to the armed-not-enqueued pattern.
        """
        expected = {
            "OmniNode-ai/omniclaude",
            "OmniNode-ai/omnibase_core",
            "OmniNode-ai/omnibase_infra",
            "OmniNode-ai/omnibase_compat",
            "OmniNode-ai/omnidash",
            "OmniNode-ai/omnimarket",
        }
        assert set(QUEUE_REPOS) == expected
        assert "OmniNode-ai/onex_change_control" not in QUEUE_REPOS


class TestResolveRepos:
    """Tests for the _resolve_repos slug-validation boundary in run_armed_not_enqueued."""

    def test_valid_slug_accepted(self) -> None:
        """A valid owner/repo slug not in alias registry is accepted via fallback."""
        from _lib.run_armed_not_enqueued import _resolve_repos  # noqa: PLC0415

        result = _resolve_repos("OmniNode-ai/some-new-repo")
        assert result == ("OmniNode-ai/some-new-repo",)

    def test_malformed_slug_trailing_slash_exits(self) -> None:
        """A slug like 'owner/' (trailing slash) must exit with code 1."""
        from _lib.run_armed_not_enqueued import _resolve_repos  # noqa: PLC0415

        with pytest.raises(SystemExit) as exc_info:
            _resolve_repos("owner/")
        assert exc_info.value.code == 1

    def test_malformed_slug_extra_slash_exits(self) -> None:
        """A slug like 'owner/repo/extra' (too many slashes) must exit with code 1."""
        from _lib.run_armed_not_enqueued import _resolve_repos  # noqa: PLC0415

        with pytest.raises(SystemExit) as exc_info:
            _resolve_repos("owner/repo/extra")
        assert exc_info.value.code == 1

    def test_malformed_slug_no_slash_no_alias_exits(self) -> None:
        """A slug with no slash that isn't a registered alias exits with code 1."""
        from _lib.run_armed_not_enqueued import _resolve_repos  # noqa: PLC0415

        with pytest.raises(SystemExit) as exc_info:
            _resolve_repos("just-a-name-no-slash")
        assert exc_info.value.code == 1
