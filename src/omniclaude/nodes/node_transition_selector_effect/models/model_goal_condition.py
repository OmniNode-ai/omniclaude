# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Goal condition model for graph navigation.

NOTE: This is a local definition pending omnibase_core export (OMN-2540).
Once omnibase_core publishes GoalCondition, replace this with:
    from omnibase_core.navigation import GoalCondition
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelGoalCondition(BaseModel):
    """Represents a goal condition in the navigation graph.

    A goal condition describes the target state the navigation loop is
    attempting to reach. It is passed to the transition selector so the
    model can evaluate which typed action best advances toward the goal.

    This is a local stub matching the spec from OMN-2540.

    Attributes:
        goal_id: Unique identifier for this goal condition.
        summary: Human-readable summary of the goal (included in prompts).
        target_state_id: Optional ID of the target state, if known.
        conditions: Key-value pairs describing the goal conditions.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    goal_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier for this goal condition",
    )
    summary: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Human-readable summary of the goal (included in prompts)",
    )
    target_state_id: str | None = Field(
        default=None,
        description="Optional ID of the target state, if known",
    )
    conditions: dict[str, str] = Field(
        default_factory=dict,
        description="Key-value pairs describing the goal conditions",
    )


__all__ = ["ModelGoalCondition"]
