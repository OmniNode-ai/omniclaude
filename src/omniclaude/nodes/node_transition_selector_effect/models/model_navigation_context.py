# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Navigation context model for graph traversal sessions.

NOTE: This is a local definition pending omnibase_core export (OMN-2540).
Once omnibase_core publishes NavigationContext, replace this with:
    from omnibase_core.models.navigation import NavigationContext
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelNavigationContext(BaseModel):
    """Context carried through the navigation loop for a single session.

    Passed to the TransitionSelector alongside current_state, goal, and
    action_set. Provides session metadata and optional retrieved prior paths.

    This is a local stub matching the spec from OMN-2569.

    Attributes:
        session_id: Unique ID for the current navigation session.
        step_number: Current step number within this session (0-indexed).
        goal_summary: Concise textual summary of the session goal.
        prior_paths: Previously successful paths retrieved from OmniMemory,
            if available. Format: list of action_id sequences.
        metadata: Additional context metadata.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID = Field(
        ...,
        description="Unique ID for the current navigation session",
    )
    step_number: int = Field(
        ...,
        ge=0,
        description="Current step number within this session (0-indexed)",
    )
    goal_summary: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Concise textual summary of the session goal",
    )
    prior_paths: tuple[tuple[str, ...], ...] = Field(
        default=(),
        description=(
            "Previously successful paths from OmniMemory (action_id sequences). "
            "Empty tuple when OmniMemory is unavailable."
        ),
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Additional context metadata",
    )


__all__ = ["ModelNavigationContext"]
