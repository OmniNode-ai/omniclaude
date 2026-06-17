# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-13039 (retro B-10): Epic auto-start ratchet for ticketing-triage.

The 2026-06-12 retro recorded that epic OMN-12952 sat ``Backlog`` all day
underneath 22 merged child PRs — detected twice, fixed zero times — until a
human marked it ``In Progress`` per plan P7/P8.

The ratchet makes the ticketing-triage orchestrator self-heal that class:
an unstarted epic (Backlog/Todo) with >= 1 started-or-completed child must
transition to ``In Progress`` on a single triage tick. The transition is
**monotone** — it only ever ratchets an epic forward to ``In Progress`` and
**never** auto-completes (auto-Done) an epic, even if every child is complete.

These tests pin the pure, deterministic reconciliation compute that the
orchestrator node owns.
"""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_skill_ticketing_triage_orchestrator.epic_reconcile import (
    EnumLinearStatusType,
    ModelEpicReconciliation,
    ModelEpicSnapshot,
    ModelEpicStateTransition,
    reconcile_epic_states,
)


def _epic(
    epic_id: str,
    status: EnumLinearStatusType,
    child_statuses: list[EnumLinearStatusType],
) -> ModelEpicSnapshot:
    return ModelEpicSnapshot(
        epic_id=epic_id,
        status_type=status,
        child_status_types=tuple(child_statuses),
    )


@pytest.mark.unit
def test_unstarted_epic_with_started_child_becomes_in_progress() -> None:
    """The headline DoD case: Backlog epic + started child -> In Progress on one tick.

    This is the OMN-12952 shape and MUST self-heal on the first sweep tick.
    """
    snapshot = _epic(
        "OMN-12952",
        EnumLinearStatusType.BACKLOG,
        [EnumLinearStatusType.STARTED],
    )

    result = reconcile_epic_states([snapshot])

    assert isinstance(result, ModelEpicReconciliation)
    assert len(result.transitions) == 1
    transition = result.transitions[0]
    assert isinstance(transition, ModelEpicStateTransition)
    assert transition.epic_id == "OMN-12952"
    assert transition.from_status_type == EnumLinearStatusType.BACKLOG
    assert transition.to_status_type == EnumLinearStatusType.STARTED
    # The ratchet returns the human-facing target state name for the tracker call.
    assert transition.target_state_name == "In Progress"
    assert "OMN-12952" in result.transitioned_epic_ids


@pytest.mark.unit
def test_todo_epic_with_completed_child_becomes_in_progress() -> None:
    """A Todo (unstarted) epic with a completed child also ratchets to In Progress."""
    snapshot = _epic(
        "OMN-2000",
        EnumLinearStatusType.UNSTARTED,
        [EnumLinearStatusType.COMPLETED],
    )

    result = reconcile_epic_states([snapshot])

    assert result.transitioned_epic_ids == ("OMN-2000",)
    assert result.transitions[0].to_status_type == EnumLinearStatusType.STARTED


@pytest.mark.unit
def test_started_epic_is_never_auto_completed() -> None:
    """Monotone guarantee: an already-started epic is NEVER auto-Done.

    Even when every child is completed, the ratchet leaves the epic In Progress —
    completion is a human decision, not an automatic transition.
    """
    snapshot = _epic(
        "OMN-3000",
        EnumLinearStatusType.STARTED,
        [EnumLinearStatusType.COMPLETED, EnumLinearStatusType.COMPLETED],
    )

    result = reconcile_epic_states([snapshot])

    assert result.transitions == ()
    assert result.transitioned_epic_ids == ()


@pytest.mark.unit
def test_unstarted_epic_with_only_unstarted_children_is_left_alone() -> None:
    """No started/completed child means no transition — the ratchet is conservative."""
    snapshot = _epic(
        "OMN-4000",
        EnumLinearStatusType.BACKLOG,
        [EnumLinearStatusType.BACKLOG, EnumLinearStatusType.UNSTARTED],
    )

    result = reconcile_epic_states([snapshot])

    assert result.transitions == ()


@pytest.mark.unit
def test_unstarted_epic_with_no_children_is_left_alone() -> None:
    """An epic with zero children cannot ratchet — there is nothing in flight."""
    snapshot = _epic("OMN-5000", EnumLinearStatusType.BACKLOG, [])

    result = reconcile_epic_states([snapshot])

    assert result.transitions == ()


@pytest.mark.unit
def test_canceled_child_does_not_trigger_autostart() -> None:
    """A canceled child is not 'in flight' and must not ratchet the epic."""
    snapshot = _epic(
        "OMN-6000",
        EnumLinearStatusType.BACKLOG,
        [EnumLinearStatusType.CANCELED],
    )

    result = reconcile_epic_states([snapshot])

    assert result.transitions == ()


@pytest.mark.unit
def test_reconcile_is_idempotent_on_second_tick() -> None:
    """After one tick promotes the epic, a second tick over the new state is a no-op.

    Models the steady state: once the epic is In Progress, repeated sweeps make
    no further transition (no flapping, no auto-Done).
    """
    first = _epic(
        "OMN-12952",
        EnumLinearStatusType.BACKLOG,
        [EnumLinearStatusType.STARTED],
    )
    result_one = reconcile_epic_states([first])
    assert result_one.transitioned_epic_ids == ("OMN-12952",)

    # Second tick: the epic is now started; same children.
    second = _epic(
        "OMN-12952",
        EnumLinearStatusType.STARTED,
        [EnumLinearStatusType.STARTED],
    )
    result_two = reconcile_epic_states([second])
    assert result_two.transitions == ()


@pytest.mark.unit
def test_mixed_batch_only_eligible_epics_transition() -> None:
    """Across a batch, only epics matching the ratchet rule transition; order is stable."""
    snapshots = [
        _epic("OMN-100", EnumLinearStatusType.BACKLOG, [EnumLinearStatusType.STARTED]),
        _epic(
            "OMN-200", EnumLinearStatusType.STARTED, [EnumLinearStatusType.COMPLETED]
        ),
        _epic("OMN-300", EnumLinearStatusType.BACKLOG, [EnumLinearStatusType.BACKLOG]),
        _epic(
            "OMN-400",
            EnumLinearStatusType.UNSTARTED,
            [EnumLinearStatusType.COMPLETED],
        ),
    ]

    result = reconcile_epic_states(snapshots)

    assert result.transitioned_epic_ids == ("OMN-100", "OMN-400")
