# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Input model for NodeTransitionSelectorEffect."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_transition_selector_effect.models.model_contract_state import (
    ModelContractState,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_goal_condition import (
    ModelGoalCondition,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_navigation_context import (
    ModelNavigationContext,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ModelTypedAction,
)


class ModelTransitionSelectorRequest(BaseModel):
    """Input model for the transition selector effect node.

    Carries all inputs needed for a single selection call. The action_set
    must be non-empty and contain only the valid transitions the model may
    choose from.

    Attributes:
        current_state: The current contract state in the navigation graph.
        goal: The goal condition this session is working toward.
        action_set: The bounded set of typed actions to select from.
            Must be non-empty. The model may only select from this set.
        context: Navigation session context (session ID, step, prior paths).
        correlation_id: Correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    current_state: ModelContractState = Field(
        ...,
        description="Current contract state in the navigation graph",
    )
    goal: ModelGoalCondition = Field(
        ...,
        description="Goal condition this session is working toward",
    )
    action_set: tuple[ModelTypedAction, ...] = Field(
        ...,
        min_length=1,
        description=(
            "Bounded set of typed actions to select from. "
            "Must be non-empty. Model may only select from this set."
        ),
    )
    context: ModelNavigationContext = Field(
        ...,
        description="Navigation session context",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for tracing",
    )


__all__ = ["ModelTransitionSelectorRequest"]
