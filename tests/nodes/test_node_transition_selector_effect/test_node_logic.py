# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for NodeTransitionSelectorEffect node logic.

Tests prompt construction and output parsing without calling the live model.
All model calls are mocked or bypassed.

Coverage:
- _build_action_list: numbered formatting
- _format_prior_paths: empty and populated
- _build_prompt: full prompt construction, constraint invariants
- _parse_selection: valid JSON, malformed JSON, out-of-set, string coercion
- select(): timeout path, malformed path, out-of-set path (via mocked _call_model)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

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
    SelectionErrorKind,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ActionCategory,
    ModelTypedAction,
)
from omniclaude.nodes.node_transition_selector_effect.node import (
    NodeTransitionSelectorEffect,
)

pytestmark = pytest.mark.unit

# =============================================================================
# Fixtures
# =============================================================================


def make_state() -> ModelContractState:
    return ModelContractState(
        state_id="state-alpha",
        node_type="Effect",
        fields={"status": "pending"},
    )


def make_goal() -> ModelGoalCondition:
    return ModelGoalCondition(
        goal_id="goal-test",
        summary="Transition to data compute node",
        target_state_id="state-beta",
    )


def make_action(
    idx: int = 1, category: ActionCategory = ActionCategory.STATE_TRANSITION
) -> ModelTypedAction:
    return ModelTypedAction(
        action_id=f"action-{idx:03d}",
        action_type="transition_to_effect",
        category=category,
        description=f"Move to state {idx + 1}",
        target_state_id=f"state-{idx + 1:03d}",
    )


def make_context(step: int = 0) -> ModelNavigationContext:
    return ModelNavigationContext(
        session_id=uuid4(),
        step_number=step,
        goal_summary="Reach compute state",
    )


def make_request(
    num_actions: int = 3,
    step: int = 0,
) -> ModelTransitionSelectorRequest:
    return ModelTransitionSelectorRequest(
        current_state=make_state(),
        goal=make_goal(),
        action_set=tuple(make_action(i) for i in range(1, num_actions + 1)),
        context=make_context(step=step),
        correlation_id=uuid4(),
    )


def make_node() -> NodeTransitionSelectorEffect:
    """Create a NodeTransitionSelectorEffect without a real container."""
    container = MagicMock()
    node = NodeTransitionSelectorEffect.__new__(NodeTransitionSelectorEffect)
    node._container = container  # type: ignore[attr-defined]
    node._llm_endpoint = "http://test-endpoint:8001"
    return node


# =============================================================================
# _build_action_list Tests
# =============================================================================


class TestBuildActionList:
    def test_single_action(self) -> None:
        action = make_action(1)
        result = NodeTransitionSelectorEffect._build_action_list((action,))
        assert "1." in result
        assert "Move to state 2" in result
        assert action.action_type in result

    def test_multiple_actions_numbered(self) -> None:
        actions = tuple(make_action(i) for i in range(1, 4))
        result = NodeTransitionSelectorEffect._build_action_list(actions)
        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert lines[0].startswith("1.")
        assert lines[1].startswith("2.")
        assert lines[2].startswith("3.")

    def test_target_state_in_output(self) -> None:
        action = make_action(1)
        result = NodeTransitionSelectorEffect._build_action_list((action,))
        assert "state-002" in result

    def test_no_target_state_shows_na(self) -> None:
        action = ModelTypedAction(
            action_id="a1",
            action_type="check",
            category=ActionCategory.BOUNDARY_CHECK,
            description="Boundary check",
        )
        result = NodeTransitionSelectorEffect._build_action_list((action,))
        assert "n/a" in result

    def test_action_type_included(self) -> None:
        action = make_action(1, category=ActionCategory.FIELD_UPDATE)
        result = NodeTransitionSelectorEffect._build_action_list((action,))
        assert "transition_to_effect" in result


# =============================================================================
# _format_prior_paths Tests
# =============================================================================


class TestFormatPriorPaths:
    def test_empty_paths(self) -> None:
        result = NodeTransitionSelectorEffect._format_prior_paths(())
        assert "None available" in result

    def test_single_path(self) -> None:
        paths = (("action-001", "action-002"),)
        result = NodeTransitionSelectorEffect._format_prior_paths(paths)
        assert "action-001" in result
        assert "action-002" in result
        assert "Path 1" in result

    def test_multiple_paths(self) -> None:
        paths = (
            ("action-001", "action-002"),
            ("action-003",),
            ("action-004", "action-005"),
        )
        result = NodeTransitionSelectorEffect._format_prior_paths(paths)
        assert "Path 1" in result
        assert "Path 2" in result
        assert "Path 3" in result

    def test_caps_at_three_paths(self) -> None:
        paths = tuple((f"action-{i:03d}",) for i in range(10))
        result = NodeTransitionSelectorEffect._format_prior_paths(paths)
        # Only first 3 shown
        assert "Path 4" not in result
        assert "Path 1" in result
        assert "Path 3" in result


# =============================================================================
# _build_prompt Tests
# =============================================================================


class TestBuildPrompt:
    def test_prompt_contains_state_id(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        assert "state-alpha" in prompt

    def test_prompt_contains_goal_summary(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        assert "Transition to data compute node" in prompt

    def test_prompt_contains_action_numbers(self) -> None:
        node = make_node()
        req = make_request(num_actions=3)
        prompt = node._build_prompt(req)
        assert "1." in prompt
        assert "2." in prompt
        assert "3." in prompt

    def test_prompt_contains_response_format(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        assert '"selected"' in prompt
        assert "JSON" in prompt

    def test_prompt_contains_session_id(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        assert str(req.context.session_id) in prompt

    def test_prompt_contains_step_number(self) -> None:
        node = make_node()
        req = make_request(step=7)
        prompt = node._build_prompt(req)
        assert "7" in prompt

    def test_prompt_contains_target_state(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        assert "state-beta" in prompt

    def test_prompt_instructs_no_free_form(self) -> None:
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        # Constraint: model must not invent transitions
        assert "Do NOT invent" in prompt

    def test_prompt_no_external_data(self) -> None:
        """Prompt must not contain data from outside current_state/goal/action_set/context."""
        node = make_node()
        req = make_request()
        prompt = node._build_prompt(req)
        # Should not contain any hardcoded external values
        assert "192.168.86.201" not in prompt  # onex-allow-internal-ip
        assert "qwen3-14b" not in prompt


# =============================================================================
# _parse_selection Tests
# =============================================================================


class TestParseSelection:
    def test_valid_json_integer(self) -> None:
        raw = '{"selected": 2}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result == 2

    def test_valid_json_first_action(self) -> None:
        raw = '{"selected": 1}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result == 1

    def test_json_with_surrounding_text(self) -> None:
        raw = 'Thinking...\n{"selected": 3}\nDone.'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result == 3

    def test_malformed_json_returns_none(self) -> None:
        raw = "I think option 2 is best."
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = NodeTransitionSelectorEffect._parse_selection("")
        assert result is None

    def test_whitespace_only_returns_none(self) -> None:
        result = NodeTransitionSelectorEffect._parse_selection("   ")
        assert result is None

    def test_wrong_key_returns_none(self) -> None:
        raw = '{"choice": 1}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result is None

    def test_string_integer_coerced(self) -> None:
        raw = '{"selected": "2"}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result == 2

    def test_non_integer_float_coerces_if_possible(self) -> None:
        raw = '{"selected": 1.0}'
        # float(1.0) -> int via coercion
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        # json.loads parses 1.0 as float; _parse_selection should handle
        # We accept either None or 1 depending on coercion — verify no crash
        assert result is None or result == 1

    def test_null_selected_returns_none(self) -> None:
        raw = '{"selected": null}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result is None

    def test_nested_json_extracts_correctly(self) -> None:
        raw = '{"selected": 5, "reasoning": "action 5 is closest to goal"}'
        result = NodeTransitionSelectorEffect._parse_selection(raw)
        assert result == 5


# =============================================================================
# NodeTransitionSelectorEffect.select() Tests (mocked)
# =============================================================================


class TestSelectMocked:
    """Tests for select() logic using mocked _call_model."""

    @pytest.mark.asyncio
    async def test_select_success(self) -> None:
        node = make_node()
        req = make_request(num_actions=3)

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 2}')
        ):
            result = await node.select(req)

        assert result.success is True
        assert result.selected_action is not None
        assert result.selected_action.action_id == "action-002"
        assert result.error_kind is None

    @pytest.mark.asyncio
    async def test_select_first_action(self) -> None:
        node = make_node()
        req = make_request(num_actions=3)

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 1}')
        ):
            result = await node.select(req)

        assert result.success is True
        assert result.selected_action is not None
        assert result.selected_action.action_id == "action-001"

    @pytest.mark.asyncio
    async def test_select_last_action(self) -> None:
        node = make_node()
        req = make_request(num_actions=3)

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 3}')
        ):
            result = await node.select(req)

        assert result.success is True
        assert result.selected_action is not None
        assert result.selected_action.action_id == "action-003"

    @pytest.mark.asyncio
    async def test_select_timeout(self) -> None:
        node = make_node()
        req = make_request()

        async def slow_call(prompt: str) -> str:
            await asyncio.sleep(99)
            return '{"selected": 1}'

        with patch.object(node, "_call_model", new=slow_call):
            with patch(
                "omniclaude.nodes.node_transition_selector_effect.node._SELECTION_TIMEOUT_SECONDS",
                0.01,
            ):
                result = await node.select(req)

        assert result.success is False
        assert result.error_kind == SelectionErrorKind.SELECTION_TIMEOUT
        assert result.selected_action is None

    @pytest.mark.asyncio
    async def test_select_malformed_output(self) -> None:
        node = make_node()
        req = make_request()

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value="I pick the second option!")
        ):
            result = await node.select(req)

        assert result.success is False
        assert result.error_kind == SelectionErrorKind.MALFORMED_OUTPUT
        assert result.model_raw_output is not None

    @pytest.mark.asyncio
    async def test_select_out_of_set(self) -> None:
        node = make_node()
        req = make_request(num_actions=3)

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 99}')
        ):
            result = await node.select(req)

        assert result.success is False
        assert result.error_kind == SelectionErrorKind.OUT_OF_SET
        assert result.selected_action is None

    @pytest.mark.asyncio
    async def test_select_zero_index_out_of_set(self) -> None:
        """Index 0 is out of set (1-indexed)."""
        node = make_node()
        req = make_request(num_actions=3)

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 0}')
        ):
            result = await node.select(req)

        assert result.success is False
        assert result.error_kind == SelectionErrorKind.OUT_OF_SET

    @pytest.mark.asyncio
    async def test_select_model_unavailable(self) -> None:
        node = make_node()
        req = make_request()

        async def failing_call(prompt: str) -> str:
            raise ConnectionRefusedError("Connection refused")

        with patch.object(node, "_call_model", new=failing_call):
            result = await node.select(req)

        assert result.success is False
        assert result.error_kind == SelectionErrorKind.MODEL_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_select_carries_correlation_id(self) -> None:
        node = make_node()
        req = make_request()

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 1}')
        ):
            result = await node.select(req)

        assert result.correlation_id == req.correlation_id

    @pytest.mark.asyncio
    async def test_select_records_duration(self) -> None:
        node = make_node()
        req = make_request()

        with patch.object(
            node, "_call_model", new=AsyncMock(return_value='{"selected": 1}')
        ):
            result = await node.select(req)

        assert result.duration_ms >= 0.0


# =============================================================================
# build_request Helper Tests
# =============================================================================


class TestBuildRequest:
    def test_build_request_from_list(self) -> None:
        state = make_state()
        goal = make_goal()
        actions = [make_action(i) for i in range(1, 4)]
        ctx = make_context()

        req = NodeTransitionSelectorEffect.build_request(state, goal, actions, ctx)

        assert isinstance(req, ModelTransitionSelectorRequest)
        assert isinstance(req.action_set, tuple)
        assert len(req.action_set) == 3
        assert req.correlation_id is not None

    def test_build_request_assigns_uuid(self) -> None:
        state = make_state()
        goal = make_goal()
        actions = [make_action(1)]
        ctx = make_context()

        req1 = NodeTransitionSelectorEffect.build_request(state, goal, actions, ctx)
        req2 = NodeTransitionSelectorEffect.build_request(state, goal, actions, ctx)

        # Each call generates a unique correlation_id
        assert req1.correlation_id != req2.correlation_id
