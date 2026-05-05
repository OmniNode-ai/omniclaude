# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Pydantic models and enums for ticketing-epic-org structural guards (OMN-10544)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumProposedGroupVerdict(StrEnum):
    """Outcome of the structural classification pass over a proposed epic group."""

    AUTO_CREATE = "auto_create"
    HUMAN_GATE = "human_gate"
    STRUCTURAL_VIOLATION = "structural_violation"


class ModelTicketSummary(BaseModel):
    """Minimal ticket projection consumed by the structural guards.

    Mirrors the fields ticketing-triage emits per orphaned ticket, plus the
    label list needed to detect existing epics.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Linear identifier, e.g. OMN-10482")
    title: str = Field(description="Ticket title as it appears in Linear")
    labels: tuple[str, ...] = Field(
        default=(),
        description="Linear labels attached to the ticket (case preserved)",
    )


class ModelSecondaryCohort(BaseModel):
    """A sub-cohort surfaced by the secondary clustering pass.

    Surfaced cohorts are candidate proposed groups; they are NOT auto-applied
    when the parent group is already ambiguous — see SKILL.md.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cohort_key: str = Field(
        description=(
            "Stable cohort identifier used in reports — e.g. 'OmniStudio Phase' "
            "or 'SEAM' or 'Cross-CLI'."
        )
    )
    pattern: str = Field(
        description=(
            "Pattern that produced the cohort: one of 'phase', 'prefix-nn', "
            "'multi-word-prefix'."
        )
    )
    members: tuple[str, ...] = Field(
        description="Ticket ids that belong to this cohort, in input order",
        min_length=2,
    )


class ModelProposedEpicGroup(BaseModel):
    """A proposed epic group as produced by the prefix/label rules in SKILL.md."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_key: str = Field(
        description=(
            "Group identifier as emitted by the primary grouping rules, e.g. "
            "'EPIC', 'PLATFORM-CLEANUP', 'ambiguous'."
        )
    )
    members: tuple[ModelTicketSummary, ...] = Field(
        description="Tickets the primary pass placed in this group",
        min_length=1,
    )


class ModelStructuralVerdict(BaseModel):
    """Verdict produced by `classify_proposed_group`.

    A `STRUCTURAL_VIOLATION` verdict means the skill MUST refuse to create a
    parent over the group — flagging is not enough.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    group_key: str = Field(description="Echoes the input group_key")
    verdict: EnumProposedGroupVerdict = Field(
        description="Classification outcome for the group"
    )
    reason: str = Field(description="Human-readable reason for the verdict")
    sub_cohorts: tuple[ModelSecondaryCohort, ...] = Field(
        default=(),
        description=(
            "Sub-cohorts surfaced by the secondary clustering pass. Empty when "
            "the group is too small or no patterns were detected."
        ),
    )
