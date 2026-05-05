# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for epic-org structural guards (OMN-10544).

Fixtures are drawn from the real 2026-05-05 epic-org smoke-test input:
``.onex_state/state/ticketing-epic-org/epic-org-2026-05-05-1.yaml``. The
"EPIC" group of 10 epics and the "ambiguous" group containing OmniStudio
Phase / SEAM / Cross-CLI sub-cohorts are reproduced verbatim so the guards
exercise the exact data that motivated the ticket.
"""

from __future__ import annotations

import pytest

from omniclaude.epic_org.guards import (
    classify_proposed_group,
    is_epic_ticket,
    secondary_cluster_pass,
)
from omniclaude.epic_org.models import (
    EnumProposedGroupVerdict,
    ModelProposedEpicGroup,
    ModelTicketSummary,
)

# ---------------------------------------------------------------------------
# Fixtures — verbatim from epic-org-2026-05-05-1.yaml
# ---------------------------------------------------------------------------

# The "EPIC" group reported in the 2026-05-05 evidence YAML — 10 tickets that
# are ALL themselves epics. The skill flagged but did not refuse this; the
# guard must now refuse it.
_EPIC_GROUP_MEMBERS: tuple[ModelTicketSummary, ...] = (
    ModelTicketSummary(
        id="OMN-10482",
        title="[Epic] Worktree cleanup + docs cohort",
        labels=("Epic", "omniclaude"),
    ),
    ModelTicketSummary(
        id="OMN-8286",
        title="[Epic] Plugin distribution standalone",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-5083",
        title="Epic: Outcome accountability",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-9469",
        title="[Epic] Runtime build two-phase",
        labels=("Epic", "runtime"),
    ),
    ModelTicketSummary(
        id="OMN-2223",
        title="[Epic] DB-SPLIT cleanup",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-3823",
        title="[Epic] Architecture handshake",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-3827",
        title="[Epic] Contract drift hardening",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-8771",
        title="[Epic] Onboarding & session as product",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-9801",
        title="[Epic] Overlay-driven merge_sweep A2A routing",
        labels=("Epic",),
    ),
    ModelTicketSummary(
        id="OMN-5257",
        title="[Epic] Stripe test mode wiring",
        labels=("Epic",),
    ),
)

# The "ambiguous" group reported in the 2026-05-05 evidence — hides three
# clean sub-cohorts that the secondary-cluster pass must surface.
_AMBIGUOUS_GROUP_MEMBERS: tuple[ModelTicketSummary, ...] = (
    # OmniStudio Phase ×4
    ModelTicketSummary(
        id="OMN-9908",
        title="OmniStudio Phase 1: skeleton service",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-9909",
        title="OmniStudio Phase 2: read-only contract graph",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-9910",
        title="OmniStudio Phase 3: write-back loop",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-9911",
        title="OmniStudio Phase 4: prod cutover",
        labels=(),
    ),
    # SEAM-* ×4
    ModelTicketSummary(
        id="OMN-10170",
        title="SEAM-1: collapse runtime-backed skill registry",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-10172",
        title="SEAM-2: canonical skill loader",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-10174",
        title="SEAM-9: deprecate legacy paths",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-10176",
        title="SEAM-10: migration guide",
        labels=(),
    ),
    # Cross-CLI ×3
    ModelTicketSummary(
        id="OMN-10135",
        title="Cross-CLI: bridge gemini cost surfacing",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-10152",
        title="Cross-CLI: codex tool-call adapter",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-10179",
        title="Cross-CLI bridge prompt budget",
        labels=(),
    ),
    # Real noise — does not match any cohort pattern, must be ignored
    ModelTicketSummary(
        id="OMN-7484",
        title="Random one-off bug fix",
        labels=(),
    ),
    ModelTicketSummary(
        id="OMN-4328",
        title="Improve x to do y",
        labels=(),
    ),
)


# ---------------------------------------------------------------------------
# is_epic_ticket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ticket", "expected"),
    [
        # Title-based — bracket prefix
        (
            ModelTicketSummary(id="OMN-1", title="[Epic] Foo bar"),
            True,
        ),
        # Title-based — colon prefix
        (
            ModelTicketSummary(id="OMN-2", title="Epic: Foo bar"),
            True,
        ),
        # Title with repo prefix before [Epic]
        (
            ModelTicketSummary(id="OMN-3", title="[omniclaude] [Epic] Foo bar"),
            True,
        ),
        # Label-based, plain title
        (
            ModelTicketSummary(id="OMN-4", title="Plain title", labels=("Epic",)),
            True,
        ),
        # Case-insensitive label
        (
            ModelTicketSummary(id="OMN-5", title="Plain title", labels=("epic",)),
            True,
        ),
        # Negative — no signal
        (
            ModelTicketSummary(
                id="OMN-6", title="Just a normal ticket", labels=("bug",)
            ),
            False,
        ),
        # Negative — title says "epic" mid-string but does not start with it
        (
            ModelTicketSummary(id="OMN-7", title="Refactor the epic queue", labels=()),
            False,
        ),
    ],
)
def test_is_epic_ticket(ticket: ModelTicketSummary, expected: bool) -> None:
    """is_epic_ticket detects title prefixes, repo-bracketed prefixes, and labels."""

    assert is_epic_ticket(ticket) is expected


# ---------------------------------------------------------------------------
# classify_proposed_group — epics-only refusal guard (Acceptance criterion #1)
# ---------------------------------------------------------------------------


def test_epics_only_group_is_refused_as_structural_violation() -> None:
    """The 2026-05-05 EPIC group must be refused, not auto-applied or merely flagged."""

    group = ModelProposedEpicGroup(
        group_key="EPIC",
        members=_EPIC_GROUP_MEMBERS,
    )

    verdict = classify_proposed_group(group)

    assert verdict.verdict is EnumProposedGroupVerdict.STRUCTURAL_VIOLATION
    assert verdict.group_key == "EPIC"
    assert "themselves epics" in verdict.reason
    # Refusal carries no sub-cohorts — the whole group is invalid.
    assert verdict.sub_cohorts == ()


def test_mixed_group_with_one_non_epic_is_not_refused() -> None:
    """A single non-epic member breaks the structural violation."""

    members = (
        *_EPIC_GROUP_MEMBERS[:9],
        ModelTicketSummary(
            id="OMN-99999",
            title="Plain feature ticket",
            labels=("bug",),
        ),
    )
    group = ModelProposedEpicGroup(group_key="EPIC", members=members)

    verdict = classify_proposed_group(group)

    assert verdict.verdict is not EnumProposedGroupVerdict.STRUCTURAL_VIOLATION


# ---------------------------------------------------------------------------
# secondary_cluster_pass — Acceptance criterion #2
# ---------------------------------------------------------------------------


def test_secondary_pass_surfaces_three_subcohorts_in_ambiguous_group() -> None:
    """Within the ambiguous group, three cohorts must be surfaced."""

    cohorts = secondary_cluster_pass(_AMBIGUOUS_GROUP_MEMBERS)

    by_key = {c.cohort_key: c for c in cohorts}

    assert "OmniStudio Phase" in by_key
    assert by_key["OmniStudio Phase"].pattern == "phase"
    assert set(by_key["OmniStudio Phase"].members) == {
        "OMN-9908",
        "OMN-9909",
        "OMN-9910",
        "OMN-9911",
    }

    assert "SEAM" in by_key
    assert by_key["SEAM"].pattern == "prefix-nn"
    assert set(by_key["SEAM"].members) == {
        "OMN-10170",
        "OMN-10172",
        "OMN-10174",
        "OMN-10176",
    }

    assert "Cross-CLI" in by_key
    assert by_key["Cross-CLI"].pattern == "multi-word-prefix"
    assert set(by_key["Cross-CLI"].members) == {
        "OMN-10135",
        "OMN-10152",
        "OMN-10179",
    }


def test_secondary_pass_orders_cohorts_by_descending_size_then_key() -> None:
    """Deterministic order is required for reproducible reports."""

    cohorts = secondary_cluster_pass(_AMBIGUOUS_GROUP_MEMBERS)

    sizes = [len(c.members) for c in cohorts]
    assert sizes == sorted(sizes, reverse=True)
    # Keys for any equal-size cohorts should be lexicographic
    keys_at_size_4 = [c.cohort_key for c in cohorts if len(c.members) == 4]
    assert keys_at_size_4 == sorted(keys_at_size_4)


def test_secondary_pass_short_circuits_below_min_group_size() -> None:
    """Groups below the minimum size return no cohorts at all."""

    tiny = (
        ModelTicketSummary(id="OMN-1", title="Phase 1: foo"),
        ModelTicketSummary(id="OMN-2", title="Phase 2: bar"),
    )

    assert secondary_cluster_pass(tiny) == ()


def test_secondary_pass_drops_singleton_cohorts() -> None:
    """A would-be cohort with only one match is noise, not a cohort."""

    members = (
        ModelTicketSummary(id="OMN-1", title="OmniStudio Phase 1: only"),
        ModelTicketSummary(id="OMN-2", title="Random A"),
        ModelTicketSummary(id="OMN-3", title="Random B"),
        ModelTicketSummary(id="OMN-4", title="Random C"),
    )

    assert secondary_cluster_pass(members) == ()


def test_secondary_pass_assigns_each_ticket_to_at_most_one_cohort() -> None:
    """Cohorts must be disjoint — first match wins."""

    cohorts = secondary_cluster_pass(_AMBIGUOUS_GROUP_MEMBERS)
    seen: set[str] = set()
    for cohort in cohorts:
        for ticket_id in cohort.members:
            assert ticket_id not in seen, f"{ticket_id} appears in more than one cohort"
            seen.add(ticket_id)


# ---------------------------------------------------------------------------
# classify_proposed_group — secondary pass integration
# ---------------------------------------------------------------------------


def test_classify_ambiguous_group_returns_human_gate_with_three_subcohorts() -> None:
    """Re-running classification on the 2026-05-05 ambiguous group must surface
    the three sub-cohorts (OmniStudio Phase, SEAM, Cross-CLI) under a
    human_gate verdict — never auto-applied."""

    group = ModelProposedEpicGroup(
        group_key="ambiguous",
        members=_AMBIGUOUS_GROUP_MEMBERS,
    )

    verdict = classify_proposed_group(group)

    assert verdict.verdict is EnumProposedGroupVerdict.HUMAN_GATE
    assert len(verdict.sub_cohorts) == 3
    assert {c.cohort_key for c in verdict.sub_cohorts} == {
        "OmniStudio Phase",
        "SEAM",
        "Cross-CLI",
    }
