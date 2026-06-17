# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Epic auto-start ratchet for the ticketing-triage orchestrator (OMN-13039, retro B-10).

The 2026-06-12 process-failure retro recorded that epic OMN-12952 sat ``Backlog``
all day under 22 merged child PRs — detected twice, fixed zero times — until a
human marked it ``In Progress`` per plan P7/P8.

This module owns the pure, deterministic compute the orchestrator node runs each
triage tick. Given a snapshot of every epic and the status of its children, it
returns the set of monotone state transitions to apply:

* An **unstarted** epic (``backlog`` or ``unstarted``/Todo) with **>= 1
  started-or-completed child** transitions to ``started`` (Linear "In Progress").
* The ratchet is **one-way**: it only ever moves an epic forward to ``started``.
  It **never** auto-completes an epic (no auto-Done), even when every child is
  complete — completion stays a human decision.
* Epics already ``started`` or later, epics with no in-flight children, and epics
  whose only children are unstarted/canceled produce **no** transition.

The orchestrator applies the returned transitions via the project tracker
(``ModelEpicStateTransition.target_state_name`` is the human-facing target the
tracker call uses); this module performs no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Canonical Linear status-type vocabulary
# ---------------------------------------------------------------------------


class EnumLinearStatusType(StrEnum):
    """Canonical Linear workflow-state *type* values.

    Mirrors Linear's ``statusType`` taxonomy (the ``type`` of a workflow state,
    independent of its display name). Display names ("Backlog", "Todo",
    "In Progress", "In Review", "Done", "Canceled") vary per team; the *type* is
    stable and is what the ratchet reasons over.
    """

    BACKLOG = "backlog"
    UNSTARTED = "unstarted"  # "Todo" family
    STARTED = "started"  # "In Progress" / "In Review" family
    COMPLETED = "completed"  # "Done" family
    CANCELED = "canceled"


# Status types that mean an epic has NOT been started yet — candidates for the ratchet.
_UNSTARTED_TYPES: frozenset[EnumLinearStatusType] = frozenset(
    {EnumLinearStatusType.BACKLOG, EnumLinearStatusType.UNSTARTED},
)

# Child status types that count as "in flight" — at least one of these on a child
# means real work has begun under the epic, so the epic must reflect that.
_IN_FLIGHT_CHILD_TYPES: frozenset[EnumLinearStatusType] = frozenset(
    {EnumLinearStatusType.STARTED, EnumLinearStatusType.COMPLETED},
)

# Human-facing target state the ratchet promotes an unstarted epic to.
# The orchestrator passes this name to the project tracker (state lookups resolve
# by name, not by raw type).
IN_PROGRESS_STATE_NAME: str = "In Progress"


# ---------------------------------------------------------------------------
# Snapshot + result models
# ---------------------------------------------------------------------------


class ModelEpicSnapshot(BaseModel):
    """Immutable snapshot of one epic and its children at a triage tick.

    Args:
        epic_id: The epic's Linear identifier (e.g. ``"OMN-12952"``).
        status_type: The epic's current workflow-state type.
        child_status_types: The workflow-state type of every direct child issue.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    epic_id: str = Field(min_length=1)
    status_type: EnumLinearStatusType
    child_status_types: tuple[EnumLinearStatusType, ...] = Field(default=())


class ModelEpicStateTransition(BaseModel):
    """A single monotone transition the ratchet wants the orchestrator to apply.

    Args:
        epic_id: The epic to transition.
        from_status_type: The epic's current (pre-transition) workflow-state type.
        to_status_type: The target workflow-state type (always ``STARTED``).
        target_state_name: Human-facing target state name for the tracker call
            (always ``"In Progress"``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    epic_id: str = Field(min_length=1)
    from_status_type: EnumLinearStatusType
    to_status_type: EnumLinearStatusType
    target_state_name: str = Field(default=IN_PROGRESS_STATE_NAME)


class ModelEpicReconciliation(BaseModel):
    """Result of one reconciliation tick over a batch of epics.

    Args:
        transitions: The transitions to apply, in input order. Empty when no epic
            is eligible (steady state / idempotent re-tick).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    transitions: tuple[ModelEpicStateTransition, ...] = Field(default=())

    @property
    def transitioned_epic_ids(self) -> tuple[str, ...]:
        """Epic ids that have a transition, in input order."""
        return tuple(t.epic_id for t in self.transitions)


# ---------------------------------------------------------------------------
# Pure reconciliation compute
# ---------------------------------------------------------------------------


def _has_in_flight_child(snapshot: ModelEpicSnapshot) -> bool:
    """Return True if any child of the epic is started or completed."""
    return any(c in _IN_FLIGHT_CHILD_TYPES for c in snapshot.child_status_types)


def should_autostart_epic(snapshot: ModelEpicSnapshot) -> bool:
    """Return True if this epic is eligible for the auto-start ratchet.

    Eligible iff the epic is unstarted (``backlog``/``unstarted``) AND has at
    least one started-or-completed child. This is the OMN-12952 shape.
    """
    return snapshot.status_type in _UNSTARTED_TYPES and _has_in_flight_child(snapshot)


def reconcile_epic_states(
    snapshots: Iterable[ModelEpicSnapshot],
) -> ModelEpicReconciliation:
    """Compute the monotone In-Progress transitions for a batch of epics.

    For each snapshot, an unstarted epic with >= 1 started/completed child is
    transitioned to ``started`` (Linear "In Progress"). The transition is one-way:
    epics that are already started-or-later are never touched and are **never**
    auto-completed. Re-running this over the post-transition snapshot is a no-op
    (idempotent steady state).

    Args:
        snapshots: The per-epic snapshots gathered this triage tick.

    Returns:
        A ``ModelEpicReconciliation`` whose ``transitions`` lists every epic that
        must ratchet to In Progress, in input order. Empty when none are eligible.
    """
    transitions: list[ModelEpicStateTransition] = []
    for snapshot in snapshots:
        if should_autostart_epic(snapshot):
            transitions.append(
                ModelEpicStateTransition(
                    epic_id=snapshot.epic_id,
                    from_status_type=snapshot.status_type,
                    to_status_type=EnumLinearStatusType.STARTED,
                    target_state_name=IN_PROGRESS_STATE_NAME,
                ),
            )
    return ModelEpicReconciliation(transitions=tuple(transitions))


__all__ = [
    "IN_PROGRESS_STATE_NAME",
    "EnumLinearStatusType",
    "ModelEpicReconciliation",
    "ModelEpicSnapshot",
    "ModelEpicStateTransition",
    "reconcile_epic_states",
    "should_autostart_epic",
]
