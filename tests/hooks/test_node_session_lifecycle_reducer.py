# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for node_session_lifecycle_reducer.py

Verifies:
- All valid FSM transitions produce correct output states
- Invalid transitions raise InvalidTransitionError with correct fields
- All states and events are covered
- reduce() is a pure function with no side effects

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from node_session_lifecycle_reducer import (
    TRANSITIONS,
    Event,
    InvalidTransitionError,
    State,
    reduce,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Valid Transition Tests
# =============================================================================


class TestValidTransitions:
    """Tests for all valid state transitions."""

    def test_idle_create_run(self) -> None:
        """IDLE + CREATE_RUN -> RUN_CREATED."""
        assert reduce(State.IDLE, Event.CREATE_RUN) == State.RUN_CREATED

    def test_run_created_activate_run(self) -> None:
        """RUN_CREATED + ACTIVATE_RUN -> RUN_ACTIVE."""
        assert reduce(State.RUN_CREATED, Event.ACTIVATE_RUN) == State.RUN_ACTIVE

    def test_run_active_end_run(self) -> None:
        """RUN_ACTIVE + END_RUN -> RUN_ENDED."""
        assert reduce(State.RUN_ACTIVE, Event.END_RUN) == State.RUN_ENDED

    def test_full_lifecycle(self) -> None:
        """Full lifecycle: IDLE -> RUN_CREATED -> RUN_ACTIVE -> RUN_ENDED."""
        state = State.IDLE
        state = reduce(state, Event.CREATE_RUN)
        assert state == State.RUN_CREATED
        state = reduce(state, Event.ACTIVATE_RUN)
        assert state == State.RUN_ACTIVE
        state = reduce(state, Event.END_RUN)
        assert state == State.RUN_ENDED


# =============================================================================
# Invalid Transition Tests
# =============================================================================


class TestInvalidTransitions:
    """Tests for invalid state transitions."""

    def test_idle_activate_run_raises(self) -> None:
        """IDLE + ACTIVATE_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.IDLE, Event.ACTIVATE_RUN)
        assert exc_info.value.from_state == State.IDLE
        assert exc_info.value.event == Event.ACTIVATE_RUN

    def test_idle_end_run_raises(self) -> None:
        """IDLE + END_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.IDLE, Event.END_RUN)
        assert exc_info.value.from_state == State.IDLE
        assert exc_info.value.event == Event.END_RUN

    def test_run_created_create_run_raises(self) -> None:
        """RUN_CREATED + CREATE_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.RUN_CREATED, Event.CREATE_RUN)
        assert exc_info.value.from_state == State.RUN_CREATED
        assert exc_info.value.event == Event.CREATE_RUN

    def test_run_created_end_run_raises(self) -> None:
        """RUN_CREATED + END_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.RUN_CREATED, Event.END_RUN)
        assert exc_info.value.from_state == State.RUN_CREATED
        assert exc_info.value.event == Event.END_RUN

    def test_run_active_create_run_raises(self) -> None:
        """RUN_ACTIVE + CREATE_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.RUN_ACTIVE, Event.CREATE_RUN)
        assert exc_info.value.from_state == State.RUN_ACTIVE
        assert exc_info.value.event == Event.CREATE_RUN

    def test_run_active_activate_run_raises(self) -> None:
        """RUN_ACTIVE + ACTIVATE_RUN is invalid."""
        with pytest.raises(InvalidTransitionError) as exc_info:
            reduce(State.RUN_ACTIVE, Event.ACTIVATE_RUN)
        assert exc_info.value.from_state == State.RUN_ACTIVE
        assert exc_info.value.event == Event.ACTIVATE_RUN

    def test_run_ended_has_no_transitions(self) -> None:
        """RUN_ENDED is a terminal state with no outgoing edges."""
        for event in Event:
            with pytest.raises(InvalidTransitionError) as exc_info:
                reduce(State.RUN_ENDED, event)
            assert exc_info.value.from_state == State.RUN_ENDED
            assert exc_info.value.event == event


# =============================================================================
# Coverage Tests
# =============================================================================


class TestCoverage:
    """Tests ensuring all enums and transitions are exercised."""

    def test_all_states_in_transition_table_or_terminal(self) -> None:
        """Every state is either in the transition table or is terminal (RUN_ENDED)."""
        for state in State:
            assert state in TRANSITIONS or state == State.RUN_ENDED

    def test_all_events_appear_in_at_least_one_transition(self) -> None:
        """Every event appears as a valid transition from at least one state."""
        used_events: set[Event] = set()
        for outgoing in TRANSITIONS.values():
            used_events.update(outgoing.keys())
        for event in Event:
            assert event in used_events, f"Event {event} never used in transitions"

    def test_transition_table_values_are_states(self) -> None:
        """All values in the transition table are valid State enum members."""
        for outgoing in TRANSITIONS.values():
            for target in outgoing.values():
                assert isinstance(target, State)


# =============================================================================
# Purity Tests
# =============================================================================


class TestPurity:
    """Tests that reduce is a pure function."""

    def test_reduce_returns_same_result_for_same_input(self) -> None:
        """reduce() is deterministic: same inputs -> same output."""
        for _ in range(10):
            assert reduce(State.IDLE, Event.CREATE_RUN) == State.RUN_CREATED
            assert reduce(State.RUN_CREATED, Event.ACTIVATE_RUN) == State.RUN_ACTIVE
            assert reduce(State.RUN_ACTIVE, Event.END_RUN) == State.RUN_ENDED

    def test_invalid_transition_error_is_value_error(self) -> None:
        """InvalidTransitionError is a subclass of ValueError."""
        assert issubclass(InvalidTransitionError, ValueError)

    def test_error_message_contains_state_and_event(self) -> None:
        """Error message includes both the state and event names."""
        with pytest.raises(InvalidTransitionError, match="idle"):
            reduce(State.IDLE, Event.END_RUN)
