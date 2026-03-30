# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Create Linear tickets for coverage gaps with deduplication."""

from __future__ import annotations

import logging

from omniclaude.coverage.models import (
    EnumCoverageGapPriority,
    ModelCoverageGap,
    ModelCoverageScanResult,
    ModelCoverageTicketRequest,
)

logger = logging.getLogger(__name__)


def _build_ticket_title(gap: ModelCoverageGap) -> str:
    """Build a standardized ticket title for a coverage gap."""
    # Extract just the module name from the full path
    # e.g. src/omniclaude/coverage/scanner.py -> coverage.scanner
    module_name = gap.module_path
    if module_name.startswith("src/"):
        module_name = module_name[4:]
    # Strip .py and convert path to dotted notation
    module_name = module_name.removesuffix(".py").replace("/", ".")
    # Remove the top-level package name for brevity
    parts = module_name.split(".")
    if len(parts) > 1:
        module_name = ".".join(parts[1:])

    return f"test(coverage): add tests for {module_name} ({gap.repo})"


def _build_ticket_description(gap: ModelCoverageGap) -> str:
    """Build a structured ticket description with requirements and DoD."""
    priority_label = {
        EnumCoverageGapPriority.ZERO_COVERAGE: "ZERO COVERAGE - complete blind spot",
        EnumCoverageGapPriority.BELOW_TARGET: f"Below target ({gap.coverage_pct}%)",
        EnumCoverageGapPriority.RECENTLY_CHANGED: f"Recently changed, below target ({gap.coverage_pct}%)",
    }
    prio_text = priority_label.get(gap.priority, str(gap.priority))

    return f"""## Problem

Module `{gap.module_path}` in `{gap.repo}` has {gap.coverage_pct}% test coverage.
- **Priority**: {prio_text}
- **Statements**: {gap.total_statements} total, {gap.covered_statements} covered, {gap.missing_statements} missing
- **Recently changed**: {"Yes" if gap.recently_changed else "No"}

## Requirements

- Add unit tests for `{gap.module_path}`
- Target: >=80% line coverage for this module
- Tests must use `@pytest.mark.unit` marker
- Tests must be in `tests/` directory following repo conventions

## Definition of Done

- [ ] Unit tests added covering primary code paths
- [ ] Coverage for this module >= 80%
- [ ] All tests pass (`uv run pytest -m unit -v`)
- [ ] No ruff/mypy violations introduced
"""


def _map_priority_to_linear(gap_priority: EnumCoverageGapPriority) -> int:
    """Map coverage gap priority to Linear priority value.

    Linear priorities: 0=none, 1=urgent, 2=high, 3=medium, 4=low
    """
    return {
        EnumCoverageGapPriority.ZERO_COVERAGE: 2,  # High
        EnumCoverageGapPriority.RECENTLY_CHANGED: 3,  # Medium
        EnumCoverageGapPriority.BELOW_TARGET: 4,  # Low
    }.get(gap_priority, 4)


class CoverageTicketCreator:
    """Create Linear tickets for coverage gaps with dedup against existing tickets."""

    def __init__(self, *, existing_ticket_titles: list[str] | None = None) -> None:
        """Initialize with optional list of existing ticket titles for dedup.

        Args:
            existing_ticket_titles: Titles of existing Linear tickets to check
                against before creating duplicates.
        """
        self._existing_titles: set[str] = set()
        if existing_ticket_titles:
            self._existing_titles = {t.lower().strip() for t in existing_ticket_titles}

    def is_duplicate(self, gap: ModelCoverageGap) -> bool:
        """Check if a ticket already exists for this gap.

        Uses fuzzy matching on the module name to detect duplicates even if
        the title format differs slightly.
        """
        title = _build_ticket_title(gap).lower()
        if title in self._existing_titles:
            return True

        # Also check for partial matches on the module path
        # Strip src/ prefix and convert to dotted notation for matching
        module_key = gap.module_path
        if module_key.startswith("src/"):
            module_key = module_key[4:]
        module_key = module_key.removesuffix(".py").replace("/", ".").lower()
        for existing in self._existing_titles:
            if module_key in existing and gap.repo.lower() in existing:
                return True

        return False

    def build_ticket_requests(
        self,
        scan_results: list[ModelCoverageScanResult],
        *,
        max_tickets: int = 20,
    ) -> tuple[list[ModelCoverageTicketRequest], int]:
        """Build ticket requests from scan results, with dedup.

        Returns:
            Tuple of (ticket_requests, skipped_dedup_count)
        """
        all_gaps: list[ModelCoverageGap] = []
        for scan in scan_results:
            if scan.scan_error:
                continue
            all_gaps.extend(scan.gaps)

        # Sort by priority (zero first, then recently changed, then below target)
        priority_order = {
            EnumCoverageGapPriority.ZERO_COVERAGE: 0,
            EnumCoverageGapPriority.RECENTLY_CHANGED: 1,
            EnumCoverageGapPriority.BELOW_TARGET: 2,
        }
        all_gaps.sort(
            key=lambda g: (priority_order.get(g.priority, 99), g.coverage_pct)
        )

        tickets: list[ModelCoverageTicketRequest] = []
        skipped = 0

        for gap in all_gaps:
            if len(tickets) >= max_tickets:
                break

            if self.is_duplicate(gap):
                skipped += 1
                logger.info("Skipping duplicate: %s", gap.module_path)
                continue

            title = _build_ticket_title(gap)
            description = _build_ticket_description(gap)
            linear_priority = _map_priority_to_linear(gap.priority)

            labels = ["test-coverage", "auto-generated"]
            if gap.priority == EnumCoverageGapPriority.ZERO_COVERAGE:
                labels.append("zero-coverage")

            tickets.append(
                ModelCoverageTicketRequest(
                    title=title,
                    description=description,
                    repo=gap.repo,
                    priority=linear_priority,
                    labels=labels,
                    gap=gap,
                )
            )

            # Track for intra-batch dedup
            self._existing_titles.add(title.lower())

        return tickets, skipped
