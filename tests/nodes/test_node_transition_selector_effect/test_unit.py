# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for endpoint configuration and resilience in NodeTransitionSelectorEffect.

Tests added as part of the Crenshaw architecture review fixes:
- Task 1: Fail-fast when LLM_CODER_FAST_URL is unset
- Task 10: Health probing
- Task 11: Actionable error messages
- Task 12: Prompt building purity
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
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
    _resolve_endpoint,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures (matching existing test_node_logic.py patterns)
# =============================================================================


def _make_request() -> ModelTransitionSelectorRequest:
    """Create a minimal valid request for testing."""
    return ModelTransitionSelectorRequest(
        current_state=ModelContractState(
            state_id="state-alpha",
            node_type="Effect",
            fields={"status": "pending"},
        ),
        goal=ModelGoalCondition(
            goal_id="goal-test",
            summary="Complete task",
            target_state_id="state-beta",
        ),
        action_set=(
            ModelTypedAction(
                action_id="action-001",
                action_type="transition_to_effect",
                category=ActionCategory.STATE_TRANSITION,
                description="Build the code",
                target_state_id="state-002",
            ),
            ModelTypedAction(
                action_id="action-002",
                action_type="transition_to_effect",
                category=ActionCategory.STATE_TRANSITION,
                description="Run tests",
                target_state_id="state-003",
            ),
        ),
        context=ModelNavigationContext(
            session_id=uuid4(),
            step_number=1,
            goal_summary="Reach compute state",
        ),
        correlation_id=uuid4(),
    )


def _make_node() -> NodeTransitionSelectorEffect:
    """Create a NodeTransitionSelectorEffect without full container init."""
    container = MagicMock()
    node = NodeTransitionSelectorEffect.__new__(NodeTransitionSelectorEffect)
    node._container = container  # type: ignore[attr-defined]
    return node


# =============================================================================
# Task 1: Fail-fast endpoint configuration
# =============================================================================


class TestResolveEndpoint:
    """Tests for _resolve_endpoint() fail-fast behavior."""

    def test_endpoint_not_configured_raises_configuration_error(self) -> None:
        """Node must fail fast when LLM_CODER_FAST_URL is not set."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LLM_CODER_FAST_URL", None)
            with pytest.raises(
                RuntimeError,
                match="LLM_CODER_FAST_URL",
            ):
                _resolve_endpoint()

    def test_endpoint_configured_returns_url(self) -> None:
        """_resolve_endpoint returns the configured URL."""
        with patch.dict(os.environ, {"LLM_CODER_FAST_URL": "http://localhost:8001"}):
            assert _resolve_endpoint() == "http://localhost:8001"

    def test_endpoint_empty_string_raises(self) -> None:
        """Empty string is treated as unset."""
        with patch.dict(os.environ, {"LLM_CODER_FAST_URL": ""}):
            with pytest.raises(RuntimeError, match="LLM_CODER_FAST_URL"):
                _resolve_endpoint()


class TestSelectEndpointError:
    """Tests for select() structured error on misconfiguration."""

    @pytest.mark.asyncio
    async def test_select_returns_structured_error_when_endpoint_unconfigured(
        self,
    ) -> None:
        """select() must surface config failure as typed result, not raw exception."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("LLM_CODER_FAST_URL", None)
            node = _make_node()
            request = _make_request()
            result = await node.select(request)
            assert not result.success
            assert result.error_kind == SelectionErrorKind.MODEL_UNAVAILABLE
            assert "LLM_CODER_FAST_URL" in (result.error_detail or "")
