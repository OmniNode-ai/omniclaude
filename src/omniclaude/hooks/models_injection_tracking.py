# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Models for injection tracking.

Defines Pydantic models for recording pattern injection events to the
pattern_injections table via the emit daemon.

Part of OMN-1673: INJECT-004 injection tracking.
"""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from omniclaude.hooks.cohort_assignment import EnumCohort


class EnumInjectionContext(str, Enum):
    """Valid injection contexts (match DB CHECK constraint)."""

    SESSION_START = "SessionStart"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    SUBAGENT_START = "SubagentStart"


class EnumInjectionSource(str, Enum):
    """Distinguishes injection outcomes for complete telemetry.

    This enum tracks WHY an injection record was created, enabling
    proper A/B analysis with complete denominators.
    """

    CONTROL_COHORT = "control_cohort"  # Intentionally no injection (A/B control)
    NO_PATTERNS = "no_patterns"  # Treatment but nothing matched filters
    INJECTED = "injected"  # Treatment with patterns successfully injected
    ERROR = "error"  # Treatment but loading/formatting failed


class ModelInjectionRecord(BaseModel):
    """Record of a pattern injection event.

    Maps to pattern_injections table in omniintelligence database.
    All injection attempts are recorded, including control cohort and
    error cases, to enable complete A/B analysis.
    """

    injection_id: UUID = Field(description="Unique identifier for this injection event")

    # Session tracking - keep raw string, derive UUID if valid
    session_id_raw: str = Field(description="Original session ID (any format)")
    session_id_uuid: UUID | None = Field(
        default=None, description="Parsed UUID if valid"
    )
    correlation_id: UUID | None = Field(
        default=None, description="Distributed tracing correlation ID"
    )

    # What was injected
    pattern_ids: list[UUID] = Field(
        default_factory=list,
        description="UUIDs of patterns from learned_patterns table",
    )
    injection_context: EnumInjectionContext = Field(
        description="Hook event that triggered injection"
    )
    source: EnumInjectionSource = Field(
        description="Outcome type: control_cohort, no_patterns, injected, or error"
    )

    # A/B experiment tracking
    cohort: EnumCohort = Field(description="Experiment cohort: control or treatment")
    assignment_seed: int = Field(
        description="Hash value (0-99) used for deterministic cohort assignment"
    )

    # Content (renamed from compiled_content per review feedback)
    injected_content: str = Field(
        default="", description="Actual markdown content injected into session"
    )
    injected_token_count: int = Field(
        default=0, description="Token count of injected content"
    )

    model_config = {"frozen": True}


__all__ = [
    "EnumInjectionContext",
    "EnumInjectionSource",
    "ModelInjectionRecord",
]
