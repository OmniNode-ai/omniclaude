#!/usr/bin/env python3
"""Shared types for pattern injection - used by both CLI and handler.

This module contains the canonical definitions for pattern-related data types,
ensuring consistency between:
- plugins/onex/hooks/lib/context_injection_wrapper.py (CLI module)
- src/omniclaude/hooks/handler_context_injection.py (handler module)

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class PatternRecord:
    """API transfer model for learned patterns (CLI version).

    This is the CLI-independent version of the pattern API model, used by
    the shell-based pattern injector subprocess.

    Frozen to ensure immutability after creation. Validation happens
    in __post_init__ before the instance is frozen.

    Architecture Note:
        This class is INTENTIONALLY DUPLICATED for subprocess independence.
        The CLI runs as a shell subprocess and cannot import from the
        omniclaude package.

        SYNC REQUIREMENTS:
        - This MUST stay in sync with PatternRecord in:
          src/omniclaude/hooks/handler_context_injection.py (ModelPatternRecord)
        - Both have identical 9 fields and validation logic
        - See tests/hooks/test_pattern_sync.py for automated verification

        The DbPatternRecord in repository_patterns.py is a DIFFERENT model
        with 4 additional database fields (id, project_scope, created_at, updated_at).

    Attributes:
        pattern_id: Unique identifier for the pattern.
        domain: Domain/category of the pattern (e.g., "code_review", "testing").
        title: Human-readable title for the pattern.
        description: Detailed description of what the pattern represents.
        confidence: Confidence score from 0.0 to 1.0.
        usage_count: Number of times this pattern has been applied.
        success_rate: Success rate from 0.0 to 1.0.
        example_reference: Optional reference to an example (e.g., "path/to/file.py:42").
        lifecycle_state: Lifecycle state of the pattern ("validated" or "provisional").
            Defaults to None for backward compatibility. None is treated as validated
            (no dampening applied). Provisional patterns are annotated differently
            in context injection output.

    See Also:
        - ModelPatternRecord: Handler API model in src/omniclaude/hooks/handler_context_injection.py
        - DbPatternRecord: Database model (12 fields) in src/omniclaude/hooks/repository_patterns.py
    """

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None
    lifecycle_state: str | None = None

    def __post_init__(self) -> None:
        """Validate fields after initialization (runs before instance is frozen)."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if not 0.0 <= self.success_rate <= 1.0:
            raise ValueError(
                f"success_rate must be between 0.0 and 1.0, got {self.success_rate}"
            )
        if self.usage_count < 0:
            raise ValueError(
                f"usage_count must be non-negative, got {self.usage_count}"
            )


@dataclass
class LoadPatternsResult:
    """
    Result from loading patterns including source attribution.

    Attributes:
        patterns: List of filtered and sorted pattern records.
        source_files: List of files that contributed at least one pattern.
    """

    patterns: list[PatternRecord]
    source_files: list[Path]


# =============================================================================
# TypedDicts for JSON Interface
# =============================================================================


class InjectorInput(TypedDict, total=False):
    """
    Input schema for the pattern injector.

    All fields are optional with defaults applied at runtime via .get().

    Attributes:
        agent_name: Name of the agent requesting patterns.
        domain: Domain to filter patterns by (empty string for all domains).
        session_id: Current session identifier.
        project: Project root path.
        correlation_id: Correlation ID for tracing.
        max_patterns: Maximum number of patterns to include.
        min_confidence: Minimum confidence threshold for pattern inclusion.
        emit_event: Whether to emit Kafka event.
        injection_context: Hook context that triggered injection
            ('session_start' or 'user_prompt_submit').
        include_footer: Whether to append injection_id as HTML comment footer.
    """

    agent_name: str
    domain: str
    session_id: str
    project: str
    correlation_id: str
    max_patterns: int
    min_confidence: float
    emit_event: bool
    injection_context: str
    include_footer: bool


class InjectorOutput(TypedDict):
    """
    Output schema for the pattern injector.

    Attributes:
        success: Whether pattern loading succeeded.
        patterns_context: Formatted markdown context for injection.
        pattern_count: Number of patterns included.
        source: Source of patterns (file path or "none").
        retrieval_ms: Time taken to retrieve and format patterns.
        injection_id: Unique identifier for this injection event (for tracking).
        cohort: Experiment cohort assignment ('control' or 'treatment').
    """

    success: bool
    patterns_context: str
    pattern_count: int
    source: str
    retrieval_ms: int
    injection_id: str | None
    cohort: str | None


# =============================================================================
# Output Constructors
# =============================================================================


def create_empty_output(source: str = "none", retrieval_ms: int = 0) -> InjectorOutput:
    """Create an empty output for cases with no patterns."""
    return InjectorOutput(
        success=True,
        patterns_context="",
        pattern_count=0,
        source=source,
        retrieval_ms=retrieval_ms,
        injection_id=None,
        cohort=None,
    )


def create_error_output(retrieval_ms: int = 0) -> InjectorOutput:
    """Create an output for error cases (still returns success for hook compatibility)."""
    return InjectorOutput(
        success=True,  # Always success for hook compatibility
        patterns_context="",
        pattern_count=0,
        source="error",
        retrieval_ms=retrieval_ms,
        injection_id=None,
        cohort=None,
    )


__all__ = [
    "PatternRecord",
    "LoadPatternsResult",
    "InjectorInput",
    "InjectorOutput",
    "create_empty_output",
    "create_error_output",
]
