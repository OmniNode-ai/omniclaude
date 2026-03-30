# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for format_full_resume_context -- Qdrant semantic recall wiring.

Validates that the full resume context builder correctly combines data from
all three stores (Postgres session state, Memgraph conflicts, Qdrant decisions)
and respects Doctrine D7 (Qdrant is enrichment only -- never required).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from omniclaude.services.session_registry_client import (
    ModelSessionRegistryRow,
    SessionRegistryClient,
)


def _sample_entry() -> ModelSessionRegistryRow:
    """Return a realistic session registry row for testing."""
    return ModelSessionRegistryRow(
        task_id="OMN-1234",
        status="active",
        current_phase="implementing",
        worktree_path="/tmp/worktrees/OMN-1234/omniclaude",  # local-path-ok
        files_touched=["src/foo.py", "src/bar.py"],
        depends_on=["OMN-1230"],
        session_ids=["session-abc"],
        correlation_ids=["corr-111"],
        decisions=["Use approach B: extend ModelFoo"],
        last_activity=datetime(2026, 3, 27, 14, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 3, 27, 10, 0, 0, tzinfo=UTC),
    )


@pytest.mark.unit
class TestFormatFullResumeContext:
    """Test format_full_resume_context() combining all three stores."""

    def test_includes_session_state(self) -> None:
        """Postgres session state (phase, files, decisions) is always present."""
        entry = _sample_entry()
        context = SessionRegistryClient.format_full_resume_context(entry=entry)

        assert "OMN-1234" in context
        assert "implementing" in context
        assert "src/foo.py" in context
        assert "approach B" in context

    def test_includes_related_decisions(self) -> None:
        """Qdrant semantic recall results appear under related decisions."""
        entry = _sample_entry()
        related = [
            {
                "task_id": "OMN-1230",
                "decision_text": "Use Postgres for state storage",
                "score": 0.88,
            },
            {
                "task_id": "OMN-1235",
                "decision_text": "Use Redis for caching",
                "score": 0.71,
            },
        ]
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            related_decisions=related,
        )

        assert "Related decisions from other tasks" in context
        assert "OMN-1230" in context
        assert "0.88" in context
        assert "Postgres" in context
        assert "OMN-1235" in context
        assert "0.71" in context

    def test_includes_conflicts(self) -> None:
        """Memgraph file conflicts appear under conflicts section."""
        entry = _sample_entry()
        conflicts = [
            {
                "other_task_id": "OMN-5678",
                "shared_files": ["src/foo.py"],
            },
        ]
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            conflicts=conflicts,
        )

        assert "Conflicts" in context
        assert "OMN-5678" in context
        assert "src/foo.py" in context

    def test_includes_coordination_signals(self) -> None:
        """Recent coordination signals appear under while-you-were-gone."""
        entry = _sample_entry()
        signals = [
            {
                "signal_type": "pr_merged",
                "task_id": "OMN-1230",
                "reason": "merged PR #47 to omnibase_core (rebase recommended)",
            },
        ]
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            coordination_signals=signals,
        )

        assert "While you were gone" in context
        assert "OMN-1230" in context
        assert "merged PR #47" in context

    def test_full_context_all_sections(self) -> None:
        """All four sections appear when all data sources provide results."""
        entry = _sample_entry()
        related = [
            {
                "task_id": "OMN-1230",
                "decision_text": "Use Postgres for state storage",
                "score": 0.88,
            },
        ]
        conflicts = [
            {
                "other_task_id": "OMN-5678",
                "shared_files": ["src/foo.py"],
            },
        ]
        signals = [
            {
                "signal_type": "pr_merged",
                "task_id": "OMN-1230",
                "reason": "merged PR #47 to omnibase_core",
            },
        ]
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            related_decisions=related,
            conflicts=conflicts,
            coordination_signals=signals,
        )

        assert "Resuming OMN-1234" in context
        assert "Decisions made" in context
        assert "Related decisions from other tasks" in context
        assert "Conflicts" in context
        assert "While you were gone" in context

    def test_d7_decisions_optional(self) -> None:
        """Doctrine D7: Qdrant decisions are enrichment only -- omitted when empty."""
        entry = _sample_entry()
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            related_decisions=None,
        )

        assert "Resuming OMN-1234" in context
        assert "Related decisions" not in context

    def test_d7_empty_list_decisions(self) -> None:
        """Doctrine D7: Empty list also omits the related decisions section."""
        entry = _sample_entry()
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            related_decisions=[],
        )

        assert "Related decisions" not in context

    def test_no_last_activity(self) -> None:
        """Last activity shows 'unknown' when not set."""
        entry = ModelSessionRegistryRow(
            task_id="OMN-9999",
            status="active",
        )
        context = SessionRegistryClient.format_full_resume_context(entry=entry)

        assert "unknown" in context
        assert "OMN-9999" in context

    def test_no_decisions_section_when_empty(self) -> None:
        """Decisions made section is omitted when entry has no decisions."""
        entry = ModelSessionRegistryRow(
            task_id="OMN-9999",
            status="active",
            current_phase="planning",
        )
        context = SessionRegistryClient.format_full_resume_context(entry=entry)

        assert "Decisions made" not in context

    def test_score_formatting(self) -> None:
        """Related decision scores are formatted to 2 decimal places."""
        entry = _sample_entry()
        related = [
            {
                "task_id": "OMN-1230",
                "decision_text": "Test formatting",
                "score": 0.9,
            },
        ]
        context = SessionRegistryClient.format_full_resume_context(
            entry=entry,
            related_decisions=related,
        )

        assert "0.90" in context
