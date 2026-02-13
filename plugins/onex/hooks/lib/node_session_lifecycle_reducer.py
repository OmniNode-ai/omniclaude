#!/usr/bin/env python3
"""Session Lifecycle Reducer - Pure declarative FSM for session state transitions.

G2 node: Zero I/O, pure state machine logic.

State transitions:
    IDLE -> RUN_CREATED (via CREATE_RUN)
    RUN_CREATED -> RUN_ACTIVE (via ACTIVATE_RUN)
    RUN_ACTIVE -> RUN_ENDED (via END_RUN)

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter

.. versionadded:: 0.2.1
"""

from __future__ import annotations

import enum

# =============================================================================
# State and Event Enums
# =============================================================================


class State(enum.Enum):
    """Session lifecycle states."""

    IDLE = "idle"
    RUN_CREATED = "run_created"
    RUN_ACTIVE = "run_active"
    RUN_ENDED = "run_ended"


class Event(enum.Enum):
    """Session lifecycle events."""

    CREATE_RUN = "create_run"
    ACTIVATE_RUN = "activate_run"
    END_RUN = "end_run"


# =============================================================================
# Transition Table
# =============================================================================

TRANSITIONS: dict[State, dict[Event, State]] = {
    State.IDLE: {Event.CREATE_RUN: State.RUN_CREATED},
    State.RUN_CREATED: {Event.ACTIVATE_RUN: State.RUN_ACTIVE},
    State.RUN_ACTIVE: {Event.END_RUN: State.RUN_ENDED},
}


# =============================================================================
# Error Types
# =============================================================================


class InvalidTransitionError(ValueError):
    """Raised when a state transition is not permitted by the FSM."""

    def __init__(self, from_state: State, event: Event) -> None:
        self.from_state = from_state
        self.event = event
        super().__init__(
            f"Invalid transition: {from_state.value} + {event.value} (no outgoing edge)"
        )


# =============================================================================
# Reducer
# =============================================================================


def reduce(state: State, event: Event) -> State:
    """Apply an event to a state, returning the next state.

    Args:
        state: Current FSM state.
        event: Event to apply.

    Returns:
        The next state after the transition.

    Raises:
        InvalidTransitionError: If the transition is not defined in the table.
    """
    outgoing = TRANSITIONS.get(state)
    if outgoing is None:
        raise InvalidTransitionError(from_state=state, event=event)

    next_state = outgoing.get(event)
    if next_state is None:
        raise InvalidTransitionError(from_state=state, event=event)

    return next_state
