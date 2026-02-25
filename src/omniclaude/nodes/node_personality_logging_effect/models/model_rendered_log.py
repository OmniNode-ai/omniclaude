# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""RenderedLog — output of the PersonalityAdapter.

Model ownership: PRIVATE to omniclaude.

RenderedLog contains the presentation-layer rendering alongside an
immutable reference to the original event. The original event is NEVER
mutated; consumers that need the raw data always have it here.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_personality_logging_effect.models.model_log_event import (
    ModelLogEvent,
)


class ModelRenderedLog(BaseModel):
    """Output of the PersonalityAdapter.

    Attributes:
        rendered_message: The personality-transformed human-readable message.
        original_event: Immutable reference to the canonical LogEvent.
        personality_name: Name of the profile used for rendering.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rendered_message: str = Field(
        ..., description="Personality-transformed human-readable message"
    )
    original_event: ModelLogEvent = Field(
        ..., description="Immutable reference to the canonical LogEvent"
    )
    personality_name: str = Field(
        ..., description="Name of the personality profile used"
    )


__all__ = ["ModelRenderedLog"]
