# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""PersonalityProfile — phrase-pack-driven rendering profile.

Model ownership: PRIVATE to omniclaude.

Profiles control how a LogEvent is rendered into human-readable text.
Built-in profiles: default, deadpan, panic_comic.
Custom profiles are loaded from YAML phrase-pack files.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelPhrasePackEntry(BaseModel):
    """A single phrase-pack entry mapping severity to a phrase template.

    Templates use ``{message}`` as the substitution slot.
    All other slots are optional and map to ``LogEvent`` fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: str = Field(..., description="Severity level this entry applies to")
    prefix: str = Field(
        default="",
        description="Text prepended before the event message",
    )
    suffix: str = Field(
        default="",
        description="Text appended after the event message",
    )


class ModelPersonalityProfile(BaseModel):
    """Personality profile: a named set of phrase-pack entries.

    Rendering is fully deterministic — same profile + same event → identical output.
    No random selection is performed.

    Built-in profiles (assembled in PersonalityAdapter):
        - ``default``: plain text rendering, no embellishment
        - ``deadpan``:  flat-affect phrasing with clinical precision
        - ``panic_comic``: escalating alarm with dry humour
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., description="Profile identifier")
    description: str = Field(default="", description="Human-readable description")
    phrases: tuple[ModelPhrasePackEntry, ...] = Field(
        default_factory=tuple,
        description="Severity-keyed phrase entries",
    )


__all__ = ["ModelPersonalityProfile", "ModelPhrasePackEntry"]
