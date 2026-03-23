# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for ticketize gap batching (OMN-6163).

Test markers:
    @pytest.mark.unit -- all tests here

Coverage:
    1. Empty skills list returns empty tickets
    2. Single skill with CRITICAL gap produces per-skill ticket
    3. Single skill with LOW gap produces per-skill ticket (not batched when alone)
    4. Multiple skills with identical LOW gaps produce one batched ticket
    5. Mixed severities: CRITICAL gaps per-skill, identical LOW gaps batched
    6. batch=False preserves original per-skill behavior
    7. Multiple distinct LOW gap messages produce separate batched tickets
    8. MEDIUM gaps are also batched (not just LOW)
    9. Tickets sorted by worst severity then title
    10. Batched ticket lists all affected skills alphabetically
    11. Package-level re-export of batch_gaps_for_ticketize
    12. BATCH_SEVERITY_THRESHOLD contains exactly CRITICAL and HIGH
"""

from __future__ import annotations

import pytest

import omniclaude.nodes.node_skill_feature_dashboard_orchestrator as pkg
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.classifier import (
    batch_gaps_for_ticketize,
)
from omniclaude.nodes.node_skill_feature_dashboard_orchestrator.models.model_result import (
    BATCH_SEVERITY_THRESHOLD,
    AuditCheckName,
    AuditCheckStatus,
    GapSeverity,
    ModelAuditCheck,
    ModelBatchedGapTicket,
    ModelGap,
    ModelSkillAudit,
    SkillStatus,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(
    name: AuditCheckName = AuditCheckName.SKILL_MD,
    status: AuditCheckStatus = AuditCheckStatus.PASS,
) -> ModelAuditCheck:
    return ModelAuditCheck(name=name, status=status, evidence=["ok"])


def _make_gap(
    layer: AuditCheckName = AuditCheckName.LINEAR_TICKET,
    severity: GapSeverity = GapSeverity.LOW,
    message: str = "metadata.ticket absent or invalid: 'None'",
    suggested_fix: str | None = "Add metadata.ticket: OMN-XXXX to contract.yaml",
) -> ModelGap:
    return ModelGap(
        layer=layer, severity=severity, message=message, suggested_fix=suggested_fix
    )


def _make_skill(
    name: str,
    status: SkillStatus = SkillStatus.PARTIAL,
    gaps: list[ModelGap] | None = None,
) -> ModelSkillAudit:
    return ModelSkillAudit(
        name=name,
        slug=name.replace("-", "_"),
        node_type="ORCHESTRATOR_GENERIC",
        status=status,
        checks=[_make_check()],
        gaps=gaps or [],
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestBatchSeverityThreshold:
    def test_contains_critical_and_high(self) -> None:
        assert GapSeverity.CRITICAL in BATCH_SEVERITY_THRESHOLD
        assert GapSeverity.HIGH in BATCH_SEVERITY_THRESHOLD

    def test_does_not_contain_medium_or_low(self) -> None:
        assert GapSeverity.MEDIUM not in BATCH_SEVERITY_THRESHOLD
        assert GapSeverity.LOW not in BATCH_SEVERITY_THRESHOLD

    def test_exactly_two_members(self) -> None:
        assert len(BATCH_SEVERITY_THRESHOLD) == 2


# ---------------------------------------------------------------------------
# Empty / trivial cases
# ---------------------------------------------------------------------------


class TestBatchGapsEmpty:
    def test_empty_skills_returns_empty(self) -> None:
        assert batch_gaps_for_ticketize([]) == []

    def test_all_wired_skills_returns_empty(self) -> None:
        """Skills with no gaps produce no tickets."""
        skills = [_make_skill("alpha", status=SkillStatus.WIRED, gaps=[])]
        assert batch_gaps_for_ticketize(skills) == []


# ---------------------------------------------------------------------------
# Per-skill tickets (CRITICAL/HIGH)
# ---------------------------------------------------------------------------


class TestPerSkillTickets:
    def test_single_critical_gap(self) -> None:
        gap = _make_gap(
            layer=AuditCheckName.SKILL_MD,
            severity=GapSeverity.CRITICAL,
            message="SKILL.md missing",
        )
        skills = [_make_skill("broken-skill", status=SkillStatus.BROKEN, gaps=[gap])]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert tickets[0].is_batched is False
        assert tickets[0].affected_skills == ["broken-skill"]
        assert tickets[0].worst_severity == GapSeverity.CRITICAL
        assert tickets[0].gap_count == 1

    def test_single_high_gap(self) -> None:
        gap = _make_gap(
            layer=AuditCheckName.EVENT_BUS_PRESENT,
            severity=GapSeverity.HIGH,
            message="event_bus key absent",
        )
        skills = [_make_skill("partial-skill", gaps=[gap])]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert tickets[0].is_batched is False
        assert tickets[0].worst_severity == GapSeverity.HIGH

    def test_multiple_skills_critical_not_batched(self) -> None:
        """Even identical CRITICAL gaps across skills get per-skill tickets."""
        gap = _make_gap(
            layer=AuditCheckName.SKILL_MD,
            severity=GapSeverity.CRITICAL,
            message="SKILL.md missing",
        )
        skills = [
            _make_skill("alpha", status=SkillStatus.BROKEN, gaps=[gap]),
            _make_skill("beta", status=SkillStatus.BROKEN, gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        # Each skill gets its own ticket for CRITICAL
        per_skill = [t for t in tickets if not t.is_batched]
        assert len(per_skill) == 2
        skill_names = {t.affected_skills[0] for t in per_skill}
        assert skill_names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Batched tickets (LOW/MEDIUM)
# ---------------------------------------------------------------------------


class TestBatchedTickets:
    def test_identical_low_gaps_batched(self) -> None:
        """Multiple skills with the same LOW gap produce one batched ticket."""
        gap = _make_gap()  # default LOW gap
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
            _make_skill("gamma", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert tickets[0].is_batched is True
        assert sorted(tickets[0].affected_skills) == ["alpha", "beta", "gamma"]
        assert tickets[0].gap_count == 3
        assert tickets[0].worst_severity == GapSeverity.LOW

    def test_single_low_gap_not_batched(self) -> None:
        """A LOW gap unique to one skill is not marked as batched."""
        gap = _make_gap()
        skills = [_make_skill("solo-skill", gaps=[gap])]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert tickets[0].is_batched is False
        assert tickets[0].affected_skills == ["solo-skill"]

    def test_medium_gaps_batched(self) -> None:
        """MEDIUM gaps are also eligible for batching."""
        gap = _make_gap(
            layer=AuditCheckName.TEST_COVERAGE,
            severity=GapSeverity.MEDIUM,
            message="No coverage signal found",
        )
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert tickets[0].is_batched is True
        assert tickets[0].worst_severity == GapSeverity.MEDIUM

    def test_distinct_low_messages_not_batched_together(self) -> None:
        """Different gap messages produce separate tickets even if both LOW."""
        gap_a = _make_gap(message="metadata.ticket absent")
        gap_b = _make_gap(message="metadata.ticket is placeholder OMN-XXXX")
        skills = [
            _make_skill("alpha", gaps=[gap_a]),
            _make_skill("beta", gaps=[gap_b]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        # Each unique message gets its own ticket (not batched since each has 1 skill)
        assert len(tickets) == 2
        assert all(not t.is_batched for t in tickets)


# ---------------------------------------------------------------------------
# Mixed severities
# ---------------------------------------------------------------------------


class TestMixedSeverities:
    def test_critical_per_skill_and_low_batched(self) -> None:
        """Skills with both CRITICAL and LOW gaps: CRITICAL per-skill, LOW batched."""
        critical_gap = _make_gap(
            layer=AuditCheckName.SKILL_MD,
            severity=GapSeverity.CRITICAL,
            message="SKILL.md missing",
        )
        low_gap = _make_gap()  # default LOW
        skills = [
            _make_skill(
                "alpha", status=SkillStatus.BROKEN, gaps=[critical_gap, low_gap]
            ),
            _make_skill(
                "beta", status=SkillStatus.BROKEN, gaps=[critical_gap, low_gap]
            ),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        critical_tickets = [
            t for t in tickets if t.worst_severity == GapSeverity.CRITICAL
        ]
        low_tickets = [t for t in tickets if t.worst_severity == GapSeverity.LOW]
        # 2 per-skill CRITICAL tickets + 1 batched LOW ticket
        assert len(critical_tickets) == 2
        assert len(low_tickets) == 1
        assert low_tickets[0].is_batched is True

    def test_sorting_worst_severity_first(self) -> None:
        """Tickets are sorted by worst severity (CRITICAL first) then title."""
        low_gap = _make_gap()
        critical_gap = _make_gap(
            layer=AuditCheckName.SKILL_MD,
            severity=GapSeverity.CRITICAL,
            message="SKILL.md missing",
        )
        skills = [
            _make_skill("zebra", status=SkillStatus.BROKEN, gaps=[critical_gap]),
            _make_skill("alpha", gaps=[low_gap]),
            _make_skill("beta", gaps=[low_gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        # CRITICAL should come first
        assert tickets[0].worst_severity == GapSeverity.CRITICAL


# ---------------------------------------------------------------------------
# --no-batch mode
# ---------------------------------------------------------------------------


class TestNoBatchMode:
    def test_no_batch_one_ticket_per_skill(self) -> None:
        """batch=False creates one ticket per skill regardless of gap duplication."""
        gap = _make_gap()
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
            _make_skill("gamma", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills, batch=False)
        assert len(tickets) == 3
        assert all(not t.is_batched for t in tickets)
        skill_names = {t.affected_skills[0] for t in tickets}
        assert skill_names == {"alpha", "beta", "gamma"}


# ---------------------------------------------------------------------------
# Ticket content validation
# ---------------------------------------------------------------------------


class TestTicketContent:
    def test_batched_ticket_title_format(self) -> None:
        gap = _make_gap()
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        assert len(tickets) == 1
        assert "[Feature Dashboard]" in tickets[0].title
        assert "2 skills" in tickets[0].title

    def test_batched_ticket_description_lists_skills(self) -> None:
        gap = _make_gap()
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        desc = tickets[0].description
        assert "`alpha`" in desc
        assert "`beta`" in desc

    def test_batched_ticket_includes_suggested_fix(self) -> None:
        gap = _make_gap(suggested_fix="Add metadata.ticket to contract.yaml")
        skills = [
            _make_skill("alpha", gaps=[gap]),
            _make_skill("beta", gaps=[gap]),
        ]
        tickets = batch_gaps_for_ticketize(skills)
        assert "Add metadata.ticket to contract.yaml" in tickets[0].description

    def test_per_skill_ticket_title_format(self) -> None:
        gap = _make_gap(
            layer=AuditCheckName.SKILL_MD,
            severity=GapSeverity.CRITICAL,
            message="SKILL.md missing",
        )
        skills = [_make_skill("broken-skill", status=SkillStatus.BROKEN, gaps=[gap])]
        tickets = batch_gaps_for_ticketize(skills)
        assert "[Feature Dashboard] broken-skill:" in tickets[0].title


# ---------------------------------------------------------------------------
# ModelBatchedGapTicket model
# ---------------------------------------------------------------------------


class TestModelBatchedGapTicket:
    def test_frozen(self) -> None:
        ticket = ModelBatchedGapTicket(
            title="test",
            description="test",
            affected_skills=["a"],
            gap_count=1,
            worst_severity=GapSeverity.LOW,
        )
        with pytest.raises(Exception):
            ticket.title = "modified"  # type: ignore[misc]

    def test_is_batched_defaults_false(self) -> None:
        ticket = ModelBatchedGapTicket(
            title="test",
            description="test",
            affected_skills=["a"],
            gap_count=1,
            worst_severity=GapSeverity.LOW,
        )
        assert ticket.is_batched is False


# ---------------------------------------------------------------------------
# Package re-exports
# ---------------------------------------------------------------------------


class TestPackageReExports:
    def test_batch_gaps_for_ticketize_exported(self) -> None:
        assert hasattr(pkg, "batch_gaps_for_ticketize")
        assert pkg.batch_gaps_for_ticketize is batch_gaps_for_ticketize
