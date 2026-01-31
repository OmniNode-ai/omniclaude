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

from pydantic import BaseModel, ConfigDict, Field

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

    Note: This model is for event emission, not database storage.
    Pattern IDs and correlation IDs are kept as strings for simplicity
    since that's how they're passed from the handler.
    """

    injection_id: UUID = Field(description="Unique identifier for this injection event")

    # Session tracking - serializes to "session_id" for backwards compatibility
    session_id_raw: str = Field(
        serialization_alias="session_id",
        description="Original session ID (any format)",
    )
    session_id_uuid: UUID | None = Field(
        default=None,
        description="Parsed UUID if valid (not serialized in events)",
        exclude=True,
    )
    correlation_id: str = Field(
        default="", description="Distributed tracing correlation ID"
    )

    # What was injected - pattern_ids are strings (not UUIDs) for simplicity
    pattern_ids: list[str] = Field(
        default_factory=list,
        description="IDs of patterns from learned_patterns table",
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

    model_config = ConfigDict(frozen=True)


__all__ = [
    "EnumInjectionContext",
    "EnumInjectionSource",
    "ModelInjectionRecord",
]
