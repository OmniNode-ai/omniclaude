#!/usr/bin/env python3
"""Shared types for pattern injection - used by both CLI and handler.

This module contains the canonical definitions for pattern-related data types,
ensuring consistency between:
- plugins/onex/hooks/lib/learned_pattern_injector.py (CLI module)
- src/omniclaude/hooks/handler_context_injection.py (handler module)

Part of OMN-1403: Context injection for session enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

# =============================================================================
# Data Classes
# =============================================================================


@dataclass(frozen=True)
class PatternRecord:
    """
    Represents a single learned pattern from the persistence store.

    This is the canonical definition for pattern records, used by both
    the CLI injector and the async handler.

    Frozen to ensure immutability after creation. Validation happens
    in __post_init__ before the instance is frozen.

    Attributes:
        pattern_id: Unique identifier for the pattern.
        domain: Domain/category of the pattern (e.g., "code_review", "testing").
        title: Human-readable title for the pattern.
        description: Detailed description of what the pattern represents.
        confidence: Confidence score from 0.0 to 1.0.
        usage_count: Number of times this pattern has been applied.
        success_rate: Success rate from 0.0 to 1.0.
        example_reference: Optional reference to an example (e.g., "path/to/file.py:42").
    """

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None

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
class PatternFile:
    """
    Represents the structure of a learned_patterns.json file.

    Attributes:
        version: Schema version of the pattern file.
        last_updated: ISO-8601 timestamp of last update.
        patterns: List of pattern records.
    """

    version: str
    last_updated: str
    patterns: list[PatternRecord] = field(default_factory=list)


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
    """

    agent_name: str
    domain: str
    session_id: str
    project: str
    correlation_id: str
    max_patterns: int
    min_confidence: float


class InjectorOutput(TypedDict):
    """
    Output schema for the pattern injector.

    Attributes:
        success: Whether pattern loading succeeded.
        patterns_context: Formatted markdown context for injection.
        pattern_count: Number of patterns included.
        source: Source of patterns (file path or "none").
        retrieval_ms: Time taken to retrieve and format patterns.
    """

    success: bool
    patterns_context: str
    pattern_count: int
    source: str
    retrieval_ms: int


__all__ = [
    "PatternRecord",
    "PatternFile",
    "LoadPatternsResult",
    "InjectorInput",
    "InjectorOutput",
]
