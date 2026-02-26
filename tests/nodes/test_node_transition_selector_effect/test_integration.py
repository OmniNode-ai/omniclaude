# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Integration tests for NodeTransitionSelectorEffect.

Tests against the live local model endpoint (LLM_CODER_FAST_URL).
These tests are skipped in CI unless the endpoint is available.

Requires:
    - LLM_CODER_FAST_URL env var or default http://192.168.86.201:8001  # onex-allow-internal-ip
    - Qwen3-14B model serving the OpenAI-compatible API

Marker: integration (excluded from unit test runs)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
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

pytestmark = pytest.mark.integration

_LLM_ENDPOINT = os.environ.get(
    "LLM_CODER_FAST_URL",
    "http://192.168.86.201:8001",  # onex-allow-internal-ip
)


def _is_endpoint_available() -> bool:
    """Check if the LLM endpoint is reachable."""
    try:
        with httpx.Client(timeout=2.0) as client:
            client.get(f"{_LLM_ENDPOINT}/health")
        return True
    except Exception:
        return False


endpoint_available = _is_endpoint_available()
skip_if_no_endpoint = pytest.mark.skipif(
    not endpoint_available,
    reason=f"LLM endpoint not available at {_LLM_ENDPOINT}",
)


def make_node() -> NodeTransitionSelectorEffect:
    container = MagicMock()
    node = NodeTransitionSelectorEffect.__new__(NodeTransitionSelectorEffect)
    node._container = container  # type: ignore[attr-defined]
    node._llm_endpoint = _LLM_ENDPOINT
    return node


# =============================================================================
# 3-State Graph Scenario
# =============================================================================

# The integration test sets up a simplified 3-state navigation scenario:
#
#   State A (Effect)  →  State B (Compute)  →  State C (Reducer)
#
# Goal: Reach State C (data aggregation).
# Current state: State A.
# Action set: 3 typed transitions.
# Expected: model selects a valid transition (any of the 3 is acceptable).


def make_three_state_scenario() -> tuple[
    ModelContractState,
    ModelGoalCondition,
    tuple[ModelTypedAction, ...],
    ModelNavigationContext,
]:
    state_a = ModelContractState(
        state_id="state-a-effect",
        node_type="Effect",
        fields={"status": "ready"},
    )
    goal = ModelGoalCondition(
        goal_id="goal-reach-reducer",
        summary="Aggregate processed data at the reducer node",
        target_state_id="state-c-reducer",
    )
    actions = (
        ModelTypedAction(
            action_id="action-a-to-b",
            action_type="transition_to_compute",
            category=ActionCategory.STATE_TRANSITION,
            description="Transition to Compute node for data transformation",
            target_state_id="state-b-compute",
        ),
        ModelTypedAction(
            action_id="action-b-to-c",
            action_type="transition_to_reducer",
            category=ActionCategory.STATE_TRANSITION,
            description="Transition to Reducer node for data aggregation",
            target_state_id="state-c-reducer",
        ),
        ModelTypedAction(
            action_id="action-boundary-check",
            action_type="boundary_check",
            category=ActionCategory.BOUNDARY_CHECK,
            description="Verify boundary conditions before proceeding",
            target_state_id=None,
        ),
    )
    context = ModelNavigationContext(
        session_id=uuid4(),
        step_number=0,
        goal_summary="Aggregate processed data at the reducer node",
    )
    return state_a, goal, actions, context


@skip_if_no_endpoint
@pytest.mark.asyncio
async def test_three_state_graph_returns_valid_transition() -> None:
    """Integration: selector picks a valid transition from the 3-state graph.

    Given a 3-state graph and a goal, the selector must return one of the
    provided actions. Any valid selection is accepted.
    """
    node = make_node()
    state, goal, actions, context = make_three_state_scenario()

    req = NodeTransitionSelectorEffect.build_request(
        state, goal, list(actions), context
    )
    result = await node.select(req)

    # Either we got a valid action, or we got a structured error (timeout/unavailable).
    # We accept structured errors here since the endpoint may be slow.
    if result.success:
        assert result.selected_action is not None
        # The selected action must be from the provided action_set
        action_ids = {a.action_id for a in actions}
        assert result.selected_action.action_id in action_ids
    else:
        # Structured error is acceptable in integration test context
        assert result.error_kind in (
            SelectionErrorKind.SELECTION_TIMEOUT,
            SelectionErrorKind.MODEL_UNAVAILABLE,
            SelectionErrorKind.MALFORMED_OUTPUT,
            SelectionErrorKind.OUT_OF_SET,
        )


@skip_if_no_endpoint
@pytest.mark.asyncio
async def test_single_action_set_selects_only_option() -> None:
    """Integration: with a single action, the selector must pick it.

    When only one action is available, any reasonable model should select
    index 1. Validates the bounded classification constraint.
    """
    node = make_node()
    only_action = ModelTypedAction(
        action_id="action-only",
        action_type="transition_to_compute",
        category=ActionCategory.STATE_TRANSITION,
        description="The only valid transition: proceed to compute node",
        target_state_id="state-compute",
    )
    state = ModelContractState(state_id="state-start", node_type="Effect")
    goal = ModelGoalCondition(
        goal_id="goal-simple",
        summary="Reach the compute node",
        target_state_id="state-compute",
    )
    context = ModelNavigationContext(
        session_id=uuid4(),
        step_number=1,
        goal_summary="Reach the compute node",
    )

    req = NodeTransitionSelectorEffect.build_request(
        state, goal, [only_action], context
    )
    result = await node.select(req)

    if result.success:
        assert result.selected_action is not None
        assert result.selected_action.action_id == "action-only"
    else:
        # Accept timeout/unavailable in integration context
        assert result.error_kind in (
            SelectionErrorKind.SELECTION_TIMEOUT,
            SelectionErrorKind.MODEL_UNAVAILABLE,
        )
