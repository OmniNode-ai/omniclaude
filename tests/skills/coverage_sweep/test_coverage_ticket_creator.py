# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for CoverageTicketCreator."""

from __future__ import annotations

import pytest

from omniclaude.coverage.models import (
    EnumCoverageGapPriority,
    ModelCoverageGap,
    ModelCoverageScanResult,
)
from omniclaude.coverage.ticket_creator import (
    CoverageTicketCreator,
    _build_ticket_description,
    _build_ticket_title,
    _map_priority_to_linear,
)


def _make_gap(
    *,
    repo: str = "omniclaude",
    module_path: str = "src/omniclaude/hooks/schemas.py",
    coverage_pct: float = 0.0,
    total_statements: int = 50,
    priority: EnumCoverageGapPriority = EnumCoverageGapPriority.ZERO_COVERAGE,
    recently_changed: bool = False,
) -> ModelCoverageGap:
    return ModelCoverageGap(
        repo=repo,
        module_path=module_path,
        coverage_pct=coverage_pct,
        total_statements=total_statements,
        covered_statements=int(total_statements * coverage_pct / 100),
        missing_statements=int(total_statements * (100 - coverage_pct) / 100),
        priority=priority,
        recently_changed=recently_changed,
    )


def _make_scan(repo: str, gaps: list[ModelCoverageGap]) -> ModelCoverageScanResult:
    return ModelCoverageScanResult(
        repo=repo,
        repo_path=f"/tmp/{repo}",
        total_modules=10,
        modules_below_target=len(gaps),
        modules_zero_coverage=sum(1 for g in gaps if g.coverage_pct == 0.0),
        repo_average_pct=50.0,
        target_pct=50.0,
        gaps=gaps,
    )


@pytest.mark.unit
class TestBuildTicketTitle:
    """Test ticket title generation."""

    def test_standard_module(self) -> None:
        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/hooks/schemas.py"
        )
        title = _build_ticket_title(gap)
        assert title == "test(coverage): add tests for hooks.schemas (omniclaude)"

    def test_deeply_nested_module(self) -> None:
        gap = _make_gap(
            repo="omnibase_core",
            module_path="src/omnibase_core/nodes/validators/check.py",
        )
        title = _build_ticket_title(gap)
        assert (
            title
            == "test(coverage): add tests for nodes.validators.check (omnibase_core)"
        )

    def test_top_level_module(self) -> None:
        gap = _make_gap(repo="omniclaude", module_path="src/omniclaude/utils.py")
        title = _build_ticket_title(gap)
        assert title == "test(coverage): add tests for utils (omniclaude)"

    def test_module_without_src_prefix(self) -> None:
        gap = _make_gap(repo="omniclaude", module_path="omniclaude/hooks/schemas.py")
        title = _build_ticket_title(gap)
        assert title == "test(coverage): add tests for hooks.schemas (omniclaude)"


@pytest.mark.unit
class TestBuildTicketDescription:
    """Test ticket description generation."""

    def test_zero_coverage_description(self) -> None:
        gap = _make_gap(
            priority=EnumCoverageGapPriority.ZERO_COVERAGE, coverage_pct=0.0
        )
        desc = _build_ticket_description(gap)
        assert "ZERO COVERAGE" in desc
        assert "0.0%" in desc
        assert "## Requirements" in desc
        assert "## Definition of Done" in desc

    def test_below_target_description(self) -> None:
        gap = _make_gap(
            priority=EnumCoverageGapPriority.BELOW_TARGET,
            coverage_pct=30.0,
        )
        desc = _build_ticket_description(gap)
        assert "Below target" in desc
        assert "30.0%" in desc

    def test_recently_changed_description(self) -> None:
        gap = _make_gap(
            priority=EnumCoverageGapPriority.RECENTLY_CHANGED,
            coverage_pct=15.0,
            recently_changed=True,
        )
        desc = _build_ticket_description(gap)
        assert "Recently changed" in desc
        assert "Yes" in desc


@pytest.mark.unit
class TestMapPriorityToLinear:
    """Test priority mapping."""

    def test_zero_coverage_is_high(self) -> None:
        assert _map_priority_to_linear(EnumCoverageGapPriority.ZERO_COVERAGE) == 2

    def test_recently_changed_is_medium(self) -> None:
        assert _map_priority_to_linear(EnumCoverageGapPriority.RECENTLY_CHANGED) == 3

    def test_below_target_is_low(self) -> None:
        assert _map_priority_to_linear(EnumCoverageGapPriority.BELOW_TARGET) == 4


@pytest.mark.unit
class TestCoverageTicketCreatorDedup:
    """Test dedup logic."""

    def test_exact_title_match(self) -> None:
        existing = ["test(coverage): add tests for hooks.schemas (omniclaude)"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)

        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/hooks/schemas.py"
        )
        assert creator.is_duplicate(gap) is True

    def test_case_insensitive_match(self) -> None:
        existing = ["TEST(COVERAGE): ADD TESTS FOR HOOKS.SCHEMAS (OMNICLAUDE)"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)

        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/hooks/schemas.py"
        )
        assert creator.is_duplicate(gap) is True

    def test_partial_module_match(self) -> None:
        """If the module path appears in an existing ticket title, it's a duplicate."""
        existing = ["test: improve coverage for omniclaude.hooks.schemas"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)

        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/hooks/schemas.py"
        )
        assert creator.is_duplicate(gap) is True

    def test_no_match_different_module(self) -> None:
        existing = ["test(coverage): add tests for hooks.schemas (omniclaude)"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)

        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/coverage/scanner.py"
        )
        assert creator.is_duplicate(gap) is False

    def test_no_match_different_repo(self) -> None:
        """Same module path in different repo should not match."""
        existing = ["test(coverage): add tests for hooks.schemas (omnibase_core)"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)

        gap = _make_gap(
            repo="omniclaude", module_path="src/omniclaude/hooks/schemas.py"
        )
        assert creator.is_duplicate(gap) is False

    def test_empty_existing_titles(self) -> None:
        creator = CoverageTicketCreator(existing_ticket_titles=[])
        gap = _make_gap()
        assert creator.is_duplicate(gap) is False

    def test_none_existing_titles(self) -> None:
        creator = CoverageTicketCreator()
        gap = _make_gap()
        assert creator.is_duplicate(gap) is False


@pytest.mark.unit
class TestCoverageTicketCreatorBuild:
    """Test ticket request building."""

    def test_build_from_scan_results(self) -> None:
        gaps = [
            _make_gap(
                module_path="src/omniclaude/zero.py",
                coverage_pct=0.0,
                priority=EnumCoverageGapPriority.ZERO_COVERAGE,
            ),
            _make_gap(
                module_path="src/omniclaude/low.py",
                coverage_pct=20.0,
                priority=EnumCoverageGapPriority.BELOW_TARGET,
            ),
        ]
        scans = [_make_scan("omniclaude", gaps)]

        creator = CoverageTicketCreator()
        tickets, skipped = creator.build_ticket_requests(scans)

        assert len(tickets) == 2
        assert skipped == 0
        # First ticket should be for zero-coverage module
        assert tickets[0].gap.coverage_pct == 0.0
        assert "zero-coverage" in tickets[0].labels

    def test_build_respects_max_tickets(self) -> None:
        gaps = [
            _make_gap(
                module_path=f"src/omniclaude/mod{i}.py",
                coverage_pct=0.0,
                priority=EnumCoverageGapPriority.ZERO_COVERAGE,
            )
            for i in range(10)
        ]
        scans = [_make_scan("omniclaude", gaps)]

        creator = CoverageTicketCreator()
        tickets, skipped = creator.build_ticket_requests(scans, max_tickets=3)

        assert len(tickets) == 3

    def test_build_skips_duplicates(self) -> None:
        gaps = [
            _make_gap(
                module_path="src/omniclaude/hooks/schemas.py",
                coverage_pct=0.0,
                priority=EnumCoverageGapPriority.ZERO_COVERAGE,
            ),
            _make_gap(
                module_path="src/omniclaude/new_mod.py",
                coverage_pct=0.0,
                priority=EnumCoverageGapPriority.ZERO_COVERAGE,
            ),
        ]
        scans = [_make_scan("omniclaude", gaps)]

        existing = ["test(coverage): add tests for hooks.schemas (omniclaude)"]
        creator = CoverageTicketCreator(existing_ticket_titles=existing)
        tickets, skipped = creator.build_ticket_requests(scans)

        assert len(tickets) == 1
        assert skipped == 1
        assert tickets[0].gap.module_path == "src/omniclaude/new_mod.py"

    def test_build_skips_errored_scans(self) -> None:
        scan_ok = _make_scan(
            "omniclaude",
            [
                _make_gap(
                    module_path="src/omniclaude/mod.py",
                    coverage_pct=0.0,
                    priority=EnumCoverageGapPriority.ZERO_COVERAGE,
                ),
            ],
        )
        scan_err = ModelCoverageScanResult(
            repo="broken",
            repo_path="/tmp/broken",
            total_modules=0,
            modules_below_target=0,
            modules_zero_coverage=0,
            repo_average_pct=0.0,
            target_pct=50.0,
            scan_error="Repo not found",
        )

        creator = CoverageTicketCreator()
        tickets, skipped = creator.build_ticket_requests([scan_ok, scan_err])

        assert len(tickets) == 1  # Only from scan_ok

    def test_intra_batch_dedup(self) -> None:
        """If two scans produce the same module, only one ticket is created."""
        gap = _make_gap(
            module_path="src/omniclaude/dup.py",
            coverage_pct=0.0,
            priority=EnumCoverageGapPriority.ZERO_COVERAGE,
        )
        scans = [
            _make_scan("omniclaude", [gap]),
            _make_scan("omniclaude", [gap]),
        ]

        creator = CoverageTicketCreator()
        tickets, skipped = creator.build_ticket_requests(scans)

        assert len(tickets) == 1
        assert skipped == 1

    def test_build_labels_for_zero_coverage(self) -> None:
        gaps = [
            _make_gap(priority=EnumCoverageGapPriority.ZERO_COVERAGE, coverage_pct=0.0),
        ]
        scans = [_make_scan("omniclaude", gaps)]

        creator = CoverageTicketCreator()
        tickets, _ = creator.build_ticket_requests(scans)

        assert "zero-coverage" in tickets[0].labels
        assert "test-coverage" in tickets[0].labels
        assert "auto-generated" in tickets[0].labels

    def test_build_labels_for_below_target(self) -> None:
        gaps = [
            _make_gap(
                module_path="src/omniclaude/partial.py",
                priority=EnumCoverageGapPriority.BELOW_TARGET,
                coverage_pct=30.0,
            ),
        ]
        scans = [_make_scan("omniclaude", gaps)]

        creator = CoverageTicketCreator()
        tickets, _ = creator.build_ticket_requests(scans)

        assert "zero-coverage" not in tickets[0].labels
        assert "test-coverage" in tickets[0].labels

    def test_multi_repo_scan(self) -> None:
        scans = [
            _make_scan(
                "omniclaude",
                [
                    _make_gap(
                        repo="omniclaude",
                        module_path="src/omniclaude/a.py",
                        coverage_pct=0.0,
                        priority=EnumCoverageGapPriority.ZERO_COVERAGE,
                    ),
                ],
            ),
            _make_scan(
                "omnibase_core",
                [
                    _make_gap(
                        repo="omnibase_core",
                        module_path="src/omnibase_core/b.py",
                        coverage_pct=10.0,
                        priority=EnumCoverageGapPriority.BELOW_TARGET,
                    ),
                ],
            ),
        ]

        creator = CoverageTicketCreator()
        tickets, _ = creator.build_ticket_requests(scans)

        assert len(tickets) == 2
        repos = {t.repo for t in tickets}
        assert repos == {"omniclaude", "omnibase_core"}
