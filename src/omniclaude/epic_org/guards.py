# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pure-Python structural guards for the ticketing-epic-org skill (OMN-10544).

These helpers are deterministic and side-effect-free so they can be exercised
by unit tests independent of Linear. The skill SKILL.md references them as the
canonical algorithm — agents must not re-implement this logic inline.

Two behaviors are implemented here:

1. ``classify_proposed_group`` — emits an ``EnumProposedGroupVerdict``. When a
   proposed group is composed entirely of tickets that are themselves epics,
   the verdict is ``STRUCTURAL_VIOLATION`` (refuse — do not flag-and-create).
2. ``secondary_cluster_pass`` — within a single proposed group, surface
   sub-cohorts that share a finer-grained pattern (Phase ``N``, ``PREFIX-NN``,
   multi-word prefixes such as ``Cross-CLI``).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from omniclaude.epic_org.models import (
    EnumProposedGroupVerdict,
    ModelProposedEpicGroup,
    ModelSecondaryCohort,
    ModelStructuralVerdict,
    ModelTicketSummary,
)

# A ticket counts as an epic when its title starts with ``[Epic]`` or ``Epic:``
# (case-insensitive after the optional repo bracket prefix), OR a label named
# ``Epic`` is attached. The repo prefix in titles like ``[omniclaude] [Epic] X``
# is preserved by Linear, so we normalise by stripping a single ``[repo]``
# bracket before testing.
_REPO_BRACKET = re.compile(r"^\[[^\]]+\]\s*")
_EPIC_TITLE_PREFIX = re.compile(r"^(?:\[Epic\]|Epic:)\s", re.IGNORECASE)

# Minimum size for a group to be worth a secondary clustering pass at all.
_MIN_GROUP_SIZE_FOR_SECONDARY_PASS = 4

# Minimum cohort size — a sub-cohort with fewer members is noise, not a cohort.
_MIN_COHORT_SIZE = 2


def is_epic_ticket(ticket: ModelTicketSummary) -> bool:
    """Return True when the ticket itself represents an epic.

    Matches on either the ``Epic`` Linear label (case-insensitive) or a title
    that starts with ``[Epic]`` / ``Epic:``. A title is checked both as-is
    and with a leading non-Epic ``[<repo>]`` bracket removed, so titles like
    ``[omniclaude] [Epic] Foo`` are detected.
    """

    if any(label.strip().lower() == "epic" for label in ticket.labels):
        return True

    title = ticket.title.lstrip()
    if _EPIC_TITLE_PREFIX.match(title):
        return True

    bracket_match = _REPO_BRACKET.match(title)
    if bracket_match is not None:
        bracket_body = bracket_match.group(0).strip("[] ").strip()
        if bracket_body.lower() != "epic":
            stripped = title[bracket_match.end() :].lstrip()
            if _EPIC_TITLE_PREFIX.match(stripped):
                return True
    return False


def classify_proposed_group(
    group: ModelProposedEpicGroup,
) -> ModelStructuralVerdict:
    """Classify a proposed epic group structurally.

    Rules:

    * If every member of the group is itself an epic, return
      ``STRUCTURAL_VIOLATION``. The skill must REFUSE to create a parent
      over existing epics.
    * Otherwise, run the secondary clustering pass over the members and
      return ``HUMAN_GATE`` so the report can surface the sub-cohorts for
      review. Auto-creation decisions live elsewhere and are out of scope
      here — see SKILL.md Phase 3.
    """

    members = group.members
    if all(is_epic_ticket(t) for t in members):
        return ModelStructuralVerdict(
            group_key=group.group_key,
            verdict=EnumProposedGroupVerdict.STRUCTURAL_VIOLATION,
            reason=(
                f"All {len(members)} members of group '{group.group_key}' are "
                "themselves epics. Refusing to create a parent over existing "
                "epics — they should remain top-level."
            ),
            sub_cohorts=(),
        )

    cohorts = secondary_cluster_pass(members)
    if cohorts:
        reason = (
            f"Group '{group.group_key}' contains {len(cohorts)} sub-cohort"
            f"{'s' if len(cohorts) != 1 else ''} surfaced by the secondary "
            "clustering pass. Flagging for human review — do not auto-apply."
        )
    else:
        reason = (
            f"Group '{group.group_key}' has no structural violation; no "
            "sub-cohorts detected."
        )
    return ModelStructuralVerdict(
        group_key=group.group_key,
        verdict=EnumProposedGroupVerdict.HUMAN_GATE,
        reason=reason,
        sub_cohorts=cohorts,
    )


def secondary_cluster_pass(
    tickets: Iterable[ModelTicketSummary],
) -> tuple[ModelSecondaryCohort, ...]:
    """Run a secondary clustering pass over the members of a proposed group.

    Detects three pattern families:

    * ``phase`` — titles containing ``Phase <N>`` (e.g. OmniStudio Phase 1).
      The cohort key is the leading words before ``Phase``, providing a
      human-readable name like ``OmniStudio Phase``.
    * ``prefix-nn`` — short ALL-CAPS prefix followed by a digit, e.g.
      ``SEAM-1``, ``DB-SPLIT-3``. Tickets with the same prefix cluster.
    * ``multi-word-prefix`` — multi-word title prefix joined by hyphens (e.g.
      ``Cross-CLI``) that recurs across multiple tickets.

    A ticket may match multiple patterns; the first match wins to keep
    cohorts disjoint. Sub-cohorts smaller than the minimum cohort size are
    discarded. Returns cohorts in deterministic order, sorted by descending
    size and then by ``cohort_key``.
    """

    members = tuple(tickets)
    if len(members) < _MIN_GROUP_SIZE_FOR_SECONDARY_PASS:
        return ()

    phase_buckets: dict[str, list[str]] = defaultdict(list)
    prefix_buckets: dict[str, list[str]] = defaultdict(list)
    multi_word_buckets: dict[str, list[str]] = defaultdict(list)

    for ticket in members:
        title = _REPO_BRACKET.sub("", ticket.title).lstrip()

        phase_key = _extract_phase_key(title)
        if phase_key is not None:
            phase_buckets[phase_key].append(ticket.id)
            continue

        prefix_key = _extract_prefix_nn_key(title)
        if prefix_key is not None:
            prefix_buckets[prefix_key].append(ticket.id)
            continue

        multi_word_key = _extract_multi_word_prefix_key(title)
        if multi_word_key is not None:
            multi_word_buckets[multi_word_key].append(ticket.id)

    cohorts: list[ModelSecondaryCohort] = []
    for key, ids in phase_buckets.items():
        if len(ids) >= _MIN_COHORT_SIZE:
            cohorts.append(
                ModelSecondaryCohort(
                    cohort_key=key, pattern="phase", members=tuple(ids)
                )
            )
    for key, ids in prefix_buckets.items():
        if len(ids) >= _MIN_COHORT_SIZE:
            cohorts.append(
                ModelSecondaryCohort(
                    cohort_key=key, pattern="prefix-nn", members=tuple(ids)
                )
            )
    for key, ids in multi_word_buckets.items():
        if len(ids) >= _MIN_COHORT_SIZE:
            cohorts.append(
                ModelSecondaryCohort(
                    cohort_key=key,
                    pattern="multi-word-prefix",
                    members=tuple(ids),
                )
            )

    cohorts.sort(key=lambda c: (-len(c.members), c.cohort_key))
    return tuple(cohorts)


# ---------------------------------------------------------------------------
# Pattern extractors — all deterministic, all return None on no-match.
# ---------------------------------------------------------------------------

# "OmniStudio Phase 1: ..."  →  cohort_key = "OmniStudio Phase"
# "Phase 4: backfill"        →  cohort_key = "Phase"
_PHASE_RE = re.compile(
    r"^(?P<lead>(?:[A-Z][\w-]*\s+){0,3})Phase\s+\d+\b",
    re.IGNORECASE,
)


def _extract_phase_key(title: str) -> str | None:
    """Return the cohort key for a Phase-style title, or None."""

    match = _PHASE_RE.match(title)
    if match is None:
        return None
    lead = match.group("lead").strip()
    if lead:
        return f"{lead} Phase"
    return "Phase"


# "SEAM-2: ..."          →  cohort_key = "SEAM"
# "DB-SPLIT-03: ..."     →  cohort_key = "DB-SPLIT"
_PREFIX_NN_RE = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9-]+?)-\d+(?::|\s|$)")


def _extract_prefix_nn_key(title: str) -> str | None:
    """Return the cohort key for a PREFIX-NN style title, or None.

    Disjoint from Phase: the regex requires uppercase prefix + dash + digit.
    A bare ``Phase 4`` lacks the dash and is therefore handled by the phase
    extractor.
    """

    match = _PREFIX_NN_RE.match(title)
    if match is None:
        return None
    return match.group("prefix")


# "Cross-CLI: ..."      →  cohort_key = "Cross-CLI"
# "Cross-CLI bridge X"  →  cohort_key = "Cross-CLI"
_MULTI_WORD_PREFIX_RE = re.compile(r"^(?P<prefix>[A-Z][a-z]+(?:-[A-Z][A-Za-z]+)+)\b")


def _extract_multi_word_prefix_key(title: str) -> str | None:
    """Return the cohort key for a hyphenated multi-word prefix, or None."""

    match = _MULTI_WORD_PREFIX_RE.match(title)
    if match is None:
        return None
    return match.group("prefix")
