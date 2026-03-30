# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for coverage sweep models."""

from __future__ import annotations

import time

import pytest

from omniclaude.coverage.models import (
    EnumCoverageGapPriority,
    ModelCoverageCache,
    ModelCoverageGap,
    ModelCoverageScanResult,
    ModelCoverageSweepReport,
    ModelCoverageTicketRequest,
)


@pytest.mark.unit
class TestModelCoverageGap:
    """Test ModelCoverageGap validation and behavior."""

    def test_create_valid_gap(self) -> None:
        gap = ModelCoverageGap(
            repo="omniclaude",
            module_path="src/omniclaude/hooks/schemas.py",
            coverage_pct=25.0,
            total_statements=100,
            covered_statements=25,
            missing_statements=75,
            priority=EnumCoverageGapPriority.BELOW_TARGET,
        )
        assert gap.repo == "omniclaude"
        assert gap.coverage_pct == 25.0
        assert gap.recently_changed is False

    def test_zero_coverage_gap(self) -> None:
        gap = ModelCoverageGap(
            repo="omnibase_core",
            module_path="src/omnibase_core/utils.py",
            coverage_pct=0.0,
            total_statements=50,
            covered_statements=0,
            missing_statements=50,
            priority=EnumCoverageGapPriority.ZERO_COVERAGE,
        )
        assert gap.coverage_pct == 0.0
        assert gap.priority == EnumCoverageGapPriority.ZERO_COVERAGE

    def test_recently_changed_flag(self) -> None:
        gap = ModelCoverageGap(
            repo="omniclaude",
            module_path="src/omniclaude/new_module.py",
            coverage_pct=10.0,
            total_statements=30,
            covered_statements=3,
            missing_statements=27,
            priority=EnumCoverageGapPriority.RECENTLY_CHANGED,
            recently_changed=True,
        )
        assert gap.recently_changed is True

    def test_frozen_model(self) -> None:
        gap = ModelCoverageGap(
            repo="omniclaude",
            module_path="src/foo.py",
            coverage_pct=50.0,
            total_statements=10,
            covered_statements=5,
            missing_statements=5,
            priority=EnumCoverageGapPriority.BELOW_TARGET,
        )
        with pytest.raises(Exception):  # ValidationError for frozen model
            gap.coverage_pct = 99.0  # type: ignore[misc]

    def test_coverage_pct_bounds(self) -> None:
        with pytest.raises(Exception):
            ModelCoverageGap(
                repo="x",
                module_path="x.py",
                coverage_pct=101.0,
                total_statements=10,
                covered_statements=10,
                missing_statements=0,
                priority=EnumCoverageGapPriority.BELOW_TARGET,
            )

        with pytest.raises(Exception):
            ModelCoverageGap(
                repo="x",
                module_path="x.py",
                coverage_pct=-1.0,
                total_statements=10,
                covered_statements=10,
                missing_statements=0,
                priority=EnumCoverageGapPriority.BELOW_TARGET,
            )


@pytest.mark.unit
class TestModelCoverageScanResult:
    """Test ModelCoverageScanResult."""

    def test_scan_result_with_gaps(self) -> None:
        gap = ModelCoverageGap(
            repo="omniclaude",
            module_path="src/omniclaude/foo.py",
            coverage_pct=0.0,
            total_statements=20,
            covered_statements=0,
            missing_statements=20,
            priority=EnumCoverageGapPriority.ZERO_COVERAGE,
        )
        result = ModelCoverageScanResult(
            repo="omniclaude",
            repo_path="/tmp/omniclaude",
            total_modules=10,
            modules_below_target=3,
            modules_zero_coverage=1,
            repo_average_pct=65.0,
            target_pct=50.0,
            gaps=[gap],
        )
        assert result.total_modules == 10
        assert len(result.gaps) == 1
        assert result.scan_error is None

    def test_scan_result_with_error(self) -> None:
        result = ModelCoverageScanResult(
            repo="missing_repo",
            repo_path="/tmp/missing",
            total_modules=0,
            modules_below_target=0,
            modules_zero_coverage=0,
            repo_average_pct=0.0,
            target_pct=50.0,
            scan_error="Repository not found",
        )
        assert result.scan_error is not None
        assert result.gaps == []


@pytest.mark.unit
class TestModelCoverageTicketRequest:
    """Test ModelCoverageTicketRequest."""

    def test_ticket_request_valid(self) -> None:
        gap = ModelCoverageGap(
            repo="omniclaude",
            module_path="src/omniclaude/hooks/schemas.py",
            coverage_pct=0.0,
            total_statements=50,
            covered_statements=0,
            missing_statements=50,
            priority=EnumCoverageGapPriority.ZERO_COVERAGE,
        )
        ticket = ModelCoverageTicketRequest(
            title="test(coverage): add tests for hooks.schemas (omniclaude)",
            description="Add unit tests",
            repo="omniclaude",
            priority=2,
            labels=["test-coverage", "auto-generated"],
            gap=gap,
        )
        assert ticket.priority == 2
        assert "test-coverage" in ticket.labels

    def test_priority_bounds(self) -> None:
        gap = ModelCoverageGap(
            repo="x",
            module_path="x.py",
            coverage_pct=0.0,
            total_statements=10,
            covered_statements=0,
            missing_statements=10,
            priority=EnumCoverageGapPriority.ZERO_COVERAGE,
        )
        with pytest.raises(Exception):
            ModelCoverageTicketRequest(
                title="t",
                description="d",
                repo="x",
                priority=5,  # Out of range 0-4
                labels=[],
                gap=gap,
            )


@pytest.mark.unit
class TestModelCoverageSweepReport:
    """Test ModelCoverageSweepReport."""

    def test_empty_report(self) -> None:
        report = ModelCoverageSweepReport()
        assert report.total_gaps == 0
        assert report.tickets_created == 0
        assert report.tickets_skipped_dedup == 0

    def test_report_with_data(self) -> None:
        scan = ModelCoverageScanResult(
            repo="omniclaude",
            repo_path="/tmp/omniclaude",
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=70.0,
            target_pct=50.0,
        )
        report = ModelCoverageSweepReport(
            scans=[scan],
            total_gaps=3,
            tickets_created=2,
            tickets_skipped_dedup=1,
        )
        assert len(report.scans) == 1
        assert report.total_gaps == 3


@pytest.mark.unit
class TestModelCoverageCache:
    """Test ModelCoverageCache TTL behavior."""

    def test_fresh_cache_not_expired(self) -> None:
        scan = ModelCoverageScanResult(
            repo="omniclaude",
            repo_path="/tmp/omniclaude",
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=70.0,
            target_pct=50.0,
        )
        cache = ModelCoverageCache(
            repo="omniclaude",
            scanned_at_unix=time.time(),
            result=scan,
        )
        assert cache.is_expired(ttl_seconds=3600.0) is False

    def test_old_cache_is_expired(self) -> None:
        scan = ModelCoverageScanResult(
            repo="omniclaude",
            repo_path="/tmp/omniclaude",
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=70.0,
            target_pct=50.0,
        )
        cache = ModelCoverageCache(
            repo="omniclaude",
            scanned_at_unix=time.time() - 7200,  # 2 hours ago
            result=scan,
        )
        assert cache.is_expired(ttl_seconds=3600.0) is True

    def test_custom_ttl(self) -> None:
        scan = ModelCoverageScanResult(
            repo="omniclaude",
            repo_path="/tmp/omniclaude",
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=70.0,
            target_pct=50.0,
        )
        cache = ModelCoverageCache(
            repo="omniclaude",
            scanned_at_unix=time.time() - 120,  # 2 minutes ago
            result=scan,
        )
        assert cache.is_expired(ttl_seconds=60.0) is True
        assert cache.is_expired(ttl_seconds=300.0) is False
