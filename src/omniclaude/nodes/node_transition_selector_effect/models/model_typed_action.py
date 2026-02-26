# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Typed action model for graph navigation transitions.

NOTE: This is a local definition pending omnibase_core export (OMN-2546).
Once omnibase_core publishes TypedAction, replace this with:
    from omnibase_core.models.navigation import TypedAction
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ActionCategory(StrEnum):
    """High-level category for typed graph transitions."""

    STATE_TRANSITION = "state_transition"
    FIELD_UPDATE = "field_update"
    SUBGRAPH_INVOKE = "subgraph_invoke"
    BOUNDARY_CHECK = "boundary_check"
    GOAL_CHECK = "goal_check"


class ModelTypedAction(BaseModel):
    """Represents a single typed action in the bounded action set.

    The transition selector receives a list of these and returns exactly
    one. The model is never asked to generate free-form actions — it
    selects from this closed set only.

    This is a local stub matching the spec from OMN-2546.

    Attributes:
        action_id: Unique identifier within the current action set.
        action_type: Semantic type of this action.
        category: High-level category for grouping.
        description: Short human-readable description (shown in prompt).
        target_state_id: Target state after this action executes.
        preconditions: Optional preconditions that must be met.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier within the current action set",
    )
    action_type: str = Field(
        ...,
        min_length=1,
        description="Semantic type of this action (e.g., 'transition_to_effect')",
    )
    category: ActionCategory = Field(
        ...,
        description="High-level category for grouping in prompts",
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Short human-readable description (shown in selection prompt)",
    )
    target_state_id: str | None = Field(
        default=None,
        description="Target state after this action executes",
    )
    preconditions: dict[str, str] = Field(
        default_factory=dict,
        description="Optional preconditions that must be met before selection",
    )


__all__ = ["ActionCategory", "ModelTypedAction"]
