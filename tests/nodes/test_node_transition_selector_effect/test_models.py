# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for NodeTransitionSelectorEffect models.

Validates Pydantic model constraints for:
- ModelContractState
- ModelGoalCondition
- ModelTypedAction (ActionCategory)
- ModelNavigationContext
- ModelTransitionSelectorRequest
- ModelTransitionSelectorResult (SelectionErrorKind)
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.nodes.node_transition_selector_effect.models.model_contract_state import (
    ModelContractState,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_goal_condition import (
    ModelGoalCondition,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_navigation_context import (
    ModelNavigationContext,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_request import (
    ModelTransitionSelectorRequest,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_result import (
    ModelTransitionSelectorResult,
    SelectionErrorKind,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ActionCategory,
    ModelTypedAction,
)

pytestmark = pytest.mark.unit

# =============================================================================
# Helper Factories
# =============================================================================


def make_state(**overrides: object) -> ModelContractState:
    defaults: dict[str, object] = {
        "state_id": "state-001",
        "node_type": "Effect",
    }
    defaults.update(overrides)
    return ModelContractState(**defaults)  # type: ignore[arg-type]


def make_goal(**overrides: object) -> ModelGoalCondition:
    defaults: dict[str, object] = {
        "goal_id": "goal-001",
        "summary": "Reach the ComputeNode state for data transformation",
    }
    defaults.update(overrides)
    return ModelGoalCondition(**defaults)  # type: ignore[arg-type]


def make_action(idx: int = 1, **overrides: object) -> ModelTypedAction:
    defaults: dict[str, object] = {
        "action_id": f"action-{idx:03d}",
        "action_type": "transition_to_effect",
        "category": ActionCategory.STATE_TRANSITION,
        "description": f"Transition to effect node state {idx}",
        "target_state_id": f"state-{idx + 1:03d}",
    }
    defaults.update(overrides)
    return ModelTypedAction(**defaults)  # type: ignore[arg-type]


def make_context(**overrides: object) -> ModelNavigationContext:
    defaults: dict[str, object] = {
        "session_id": uuid4(),
        "step_number": 0,
        "goal_summary": "Transform contract data",
    }
    defaults.update(overrides)
    return ModelNavigationContext(**defaults)  # type: ignore[arg-type]


def make_request(
    num_actions: int = 3, **overrides: object
) -> ModelTransitionSelectorRequest:
    defaults: dict[str, object] = {
        "current_state": make_state(),
        "goal": make_goal(),
        "action_set": tuple(make_action(i) for i in range(1, num_actions + 1)),
        "context": make_context(),
        "correlation_id": uuid4(),
    }
    defaults.update(overrides)
    return ModelTransitionSelectorRequest(**defaults)  # type: ignore[arg-type]


# =============================================================================
# ModelContractState Tests
# =============================================================================


class TestModelContractStateValid:
    def test_minimal(self) -> None:
        state = make_state()
        assert state.state_id == "state-001"
        assert state.node_type == "Effect"
        assert state.fields == {}
        assert state.metadata == {}

    def test_with_fields(self) -> None:
        state = make_state(fields={"key": "value", "count": 3})
        assert state.fields["key"] == "value"
        assert state.fields["count"] == 3

    def test_immutable(self) -> None:
        state = make_state()
        with pytest.raises(ValidationError):
            state.state_id = "new-id"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ModelContractState(
                state_id="s1",
                node_type="Effect",
                extra_field="not allowed",  # type: ignore[call-arg]
            )


class TestModelContractStateInvalid:
    def test_empty_state_id_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_state(state_id="")
        assert "state_id" in str(exc_info.value)

    def test_empty_node_type_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_state(node_type="")
        assert "node_type" in str(exc_info.value)


# =============================================================================
# ModelGoalCondition Tests
# =============================================================================


class TestModelGoalConditionValid:
    def test_minimal(self) -> None:
        goal = make_goal()
        assert goal.goal_id == "goal-001"
        assert goal.target_state_id is None
        assert goal.conditions == {}

    def test_with_target_state(self) -> None:
        goal = make_goal(target_state_id="state-final")
        assert goal.target_state_id == "state-final"

    def test_with_conditions(self) -> None:
        goal = make_goal(conditions={"field_x": "value_y"})
        assert goal.conditions["field_x"] == "value_y"

    def test_immutable(self) -> None:
        goal = make_goal()
        with pytest.raises(ValidationError):
            goal.goal_id = "new-id"  # type: ignore[misc]


class TestModelGoalConditionInvalid:
    def test_empty_goal_id_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_goal(goal_id="")
        assert "goal_id" in str(exc_info.value)

    def test_empty_summary_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_goal(summary="")
        assert "summary" in str(exc_info.value)

    def test_summary_too_long_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_goal(summary="x" * 501)
        assert "summary" in str(exc_info.value)


# =============================================================================
# ModelTypedAction Tests
# =============================================================================


class TestModelTypedActionValid:
    def test_minimal(self) -> None:
        action = make_action()
        assert action.action_id == "action-001"
        assert action.category == ActionCategory.STATE_TRANSITION
        assert action.preconditions == {}

    def test_all_categories(self) -> None:
        for cat in ActionCategory:
            action = make_action(category=cat)
            assert action.category == cat

    def test_immutable(self) -> None:
        action = make_action()
        with pytest.raises(ValidationError):
            action.action_id = "new-id"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            ModelTypedAction(
                action_id="a1",
                action_type="test",
                category=ActionCategory.FIELD_UPDATE,
                description="test action",
                unknown_field="x",  # type: ignore[call-arg]
            )


class TestModelTypedActionInvalid:
    def test_empty_description_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_action(description="")
        assert "description" in str(exc_info.value)

    def test_description_too_long_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_action(description="x" * 301)
        assert "description" in str(exc_info.value)

    def test_empty_action_type_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_action(action_type="")
        assert "action_type" in str(exc_info.value)


# =============================================================================
# ModelNavigationContext Tests
# =============================================================================


class TestModelNavigationContextValid:
    def test_minimal(self) -> None:
        ctx = make_context()
        assert ctx.step_number == 0
        assert ctx.prior_paths == ()
        assert ctx.metadata == {}

    def test_with_prior_paths(self) -> None:
        paths = (("action-001", "action-002"), ("action-003",))
        ctx = make_context(prior_paths=paths)
        assert len(ctx.prior_paths) == 2
        assert ctx.prior_paths[0] == ("action-001", "action-002")

    def test_step_number_zero(self) -> None:
        ctx = make_context(step_number=0)
        assert ctx.step_number == 0

    def test_step_number_large(self) -> None:
        ctx = make_context(step_number=999)
        assert ctx.step_number == 999

    def test_immutable(self) -> None:
        ctx = make_context()
        with pytest.raises(ValidationError):
            ctx.step_number = 5  # type: ignore[misc]


class TestModelNavigationContextInvalid:
    def test_negative_step_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_context(step_number=-1)
        assert "step_number" in str(exc_info.value)

    def test_empty_goal_summary_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_context(goal_summary="")
        assert "goal_summary" in str(exc_info.value)

    def test_goal_summary_too_long_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_context(goal_summary="x" * 501)
        assert "goal_summary" in str(exc_info.value)


# =============================================================================
# ModelTransitionSelectorRequest Tests
# =============================================================================


class TestModelTransitionSelectorRequestValid:
    def test_minimal_request(self) -> None:
        req = make_request(num_actions=1)
        assert len(req.action_set) == 1
        assert req.correlation_id is not None

    def test_multi_action_set(self) -> None:
        req = make_request(num_actions=5)
        assert len(req.action_set) == 5

    def test_action_set_is_tuple(self) -> None:
        req = make_request(num_actions=3)
        assert isinstance(req.action_set, tuple)

    def test_immutable(self) -> None:
        req = make_request()
        with pytest.raises(ValidationError):
            req.correlation_id = uuid4()  # type: ignore[misc]


class TestModelTransitionSelectorRequestInvalid:
    def test_empty_action_set_fails(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            make_request(action_set=())
        assert "action_set" in str(exc_info.value)


# =============================================================================
# ModelTransitionSelectorResult Tests
# =============================================================================


class TestModelTransitionSelectorResultSuccess:
    def test_success_with_action(self) -> None:
        action = make_action()
        corr_id = uuid4()
        result = ModelTransitionSelectorResult(
            selected_action=action,
            duration_ms=45.0,
            correlation_id=corr_id,
        )
        assert result.success is True
        assert result.selected_action == action
        assert result.error_kind is None
        assert result.error_detail is None

    def test_success_false_when_no_action(self) -> None:
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.SELECTION_TIMEOUT,
            error_detail="Timed out after 10s",
            correlation_id=uuid4(),
        )
        assert result.success is False
        assert result.selected_action is None


class TestModelTransitionSelectorResultErrors:
    def test_timeout_error(self) -> None:
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.SELECTION_TIMEOUT,
            error_detail="Model did not respond within 10s",
            correlation_id=uuid4(),
        )
        assert result.error_kind == SelectionErrorKind.SELECTION_TIMEOUT
        assert result.success is False

    def test_malformed_output_error(self) -> None:
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.MALFORMED_OUTPUT,
            error_detail="Could not parse JSON from: 'I choose option A'",
            model_raw_output="I choose option A",
            correlation_id=uuid4(),
        )
        assert result.error_kind == SelectionErrorKind.MALFORMED_OUTPUT
        assert result.model_raw_output == "I choose option A"

    def test_out_of_set_error(self) -> None:
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.OUT_OF_SET,
            error_detail="Selected index 99 but only 3 actions available",
            model_raw_output='{"selected": 99}',
            correlation_id=uuid4(),
        )
        assert result.error_kind == SelectionErrorKind.OUT_OF_SET

    def test_all_error_kinds_valid(self) -> None:
        for kind in SelectionErrorKind:
            result = ModelTransitionSelectorResult(
                error_kind=kind,
                error_detail=f"Error: {kind}",
                correlation_id=uuid4(),
            )
            assert result.error_kind == kind

    def test_duration_ms_non_negative(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelTransitionSelectorResult(
                error_kind=SelectionErrorKind.MODEL_UNAVAILABLE,
                error_detail="Connection refused",
                duration_ms=-1.0,
                correlation_id=uuid4(),
            )
        assert "duration_ms" in str(exc_info.value)

    def test_immutable(self) -> None:
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.SELECTION_TIMEOUT,
            error_detail="Timeout",
            correlation_id=uuid4(),
        )
        with pytest.raises(ValidationError):
            result.error_kind = SelectionErrorKind.MALFORMED_OUTPUT  # type: ignore[misc]


# =============================================================================
# Serialization Tests
# =============================================================================


class TestModelSerialization:
    def test_request_roundtrip(self) -> None:
        req = make_request(num_actions=2)
        restored = ModelTransitionSelectorRequest.model_validate_json(
            req.model_dump_json()
        )
        assert len(restored.action_set) == 2
        assert restored.correlation_id == req.correlation_id

    def test_result_roundtrip_success(self) -> None:
        action = make_action()
        corr_id = uuid4()
        result = ModelTransitionSelectorResult(
            selected_action=action,
            duration_ms=33.5,
            correlation_id=corr_id,
        )
        restored = ModelTransitionSelectorResult.model_validate_json(
            result.model_dump_json()
        )
        assert restored.selected_action is not None
        assert restored.selected_action.action_id == action.action_id
        assert restored.duration_ms == 33.5
        assert restored.correlation_id == corr_id

    def test_result_roundtrip_error(self) -> None:
        corr_id = uuid4()
        result = ModelTransitionSelectorResult(
            error_kind=SelectionErrorKind.SELECTION_TIMEOUT,
            error_detail="Timed out",
            correlation_id=corr_id,
        )
        restored = ModelTransitionSelectorResult.model_validate_json(
            result.model_dump_json()
        )
        assert restored.error_kind == SelectionErrorKind.SELECTION_TIMEOUT
        assert restored.correlation_id == corr_id
