#!/usr/bin/env python3
"""Deterministic session outcome derivation from observable signals.

Derives a session outcome classification (success, failed, abandoned, unknown)
from session-end signals without any network calls or datetime.now() defaults.

Decision tree (evaluated in order):
    1. FAILED: exit_code != 0 OR error_markers detected in session output
    2. SUCCESS: tool_calls_completed > 0 AND completion_markers detected
    3. ABANDONED: no completion_markers AND duration < ABANDON_THRESHOLD_SECONDS
    4. UNKNOWN: none of the above criteria met

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# =============================================================================
# Constants
# =============================================================================

# Threshold below which a session without completion markers is considered abandoned.
# 60 seconds: a quick open-and-close with no meaningful work done.
ABANDON_THRESHOLD_SECONDS: float = 60.0

# Compiled patterns that indicate a session ended with errors.
# Each pattern controls its own anchoring and context to reduce false positives.
ERROR_MARKER_REGEXES: tuple[re.Pattern[str], ...] = (
    # "Error:", "ValueError:", "TypeError:", etc. at start of a line
    re.compile(r"(?:^|\n)\s*\w*Error:"),
    # "Exception:", "RuntimeException:", etc. at start of a line
    re.compile(r"(?:^|\n)\s*\w*Exception:"),
    # "Traceback" as a standalone word (already distinctive)
    re.compile(r"\bTraceback\b"),
    # "FAILED" with a preceding non-zero count or "test(s)" prefix.
    # Standalone FAILED at end-of-line is handled separately in _has_error_markers
    # to properly exclude zero-count prefixes with variable whitespace.
    re.compile(r"[1-9]\d*\s+FAILED\b|[Tt]ests?\s+FAILED\b"),
)

# Standalone FAILED at end of line — checked per-match in _has_error_markers
# with zero-count prefix exclusion. Separated from ERROR_MARKER_REGEXES because
# the exclusion requires per-line context that fixed-width lookbehinds cannot handle.
# Known limitation: May match "FAILED" in user prompt echo-backs.
# Mitigated by _ZERO_COUNT_PREFIX_RE exclusion and Phase 1 session_output
# not yet carrying raw stdout (currently uses session_reason codes only).
_FAILED_EOL_RE: re.Pattern[str] = re.compile(r"\bFAILED\s*$", re.MULTILINE)
_ZERO_COUNT_PREFIX_RE: re.Pattern[str] = re.compile(r"\b0+\s+FAILED\b")

# Patterns that indicate a session completed meaningful work.
# Pre-compiled with IGNORECASE and word boundaries, matching the ERROR_MARKER_REGEXES pattern.
COMPLETION_MARKER_PATTERNS: tuple[str, ...] = (
    "completed",
    "done",
    "finished",
    "success",
)
_COMPLETION_MARKER_REGEXES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"\b" + re.escape(marker) + r"\b", re.IGNORECASE)
    for marker in COMPLETION_MARKER_PATTERNS
)

# Commit hash: 7-40 lowercase hex chars, NOT preceded or followed by a dash.
# This avoids matching hex segments of UUIDs (which use dashes as separators).
_COMMIT_HASH_RE = re.compile(r"(?<!-)\b[0-9a-f]{7,40}\b(?!-)")

# Valid outcome values (matches EnumClaudeCodeSessionOutcome from omnibase_core.enums).
OUTCOME_SUCCESS = "success"
OUTCOME_FAILED = "failed"
OUTCOME_ABANDONED = "abandoned"
OUTCOME_UNKNOWN = "unknown"


# =============================================================================
# Result Type
# =============================================================================


class SessionOutcomeResult(NamedTuple):
    """Result of session outcome derivation."""

    outcome: str  # One of: success, failed, abandoned, unknown
    reason: str  # Human-readable explanation of why this outcome was chosen
    signals_used: tuple[str, ...]  # Which signals contributed to the decision


# =============================================================================
# Core Logic
# =============================================================================


def _has_error_markers(session_output: str) -> bool:
    """Check if session output contains error markers.

    Uses pre-compiled regexes with line-start anchoring and contextual
    patterns to reduce false positives from benign references to errors
    (e.g., 'fix FAILED test' or 'This is an Error: none found').

    Standalone FAILED at end-of-line is checked separately with per-line
    zero-count exclusion to handle variable whitespace (e.g., '0  FAILED').
    """
    for pattern in ERROR_MARKER_REGEXES:
        if pattern.search(session_output):
            return True
    # Check standalone FAILED at end of line, excluding lines with zero-count prefix
    for match in _FAILED_EOL_RE.finditer(session_output):
        line_start = session_output.rfind("\n", 0, match.start()) + 1
        line = session_output[line_start : match.end()]
        if not _ZERO_COUNT_PREFIX_RE.search(line):
            return True
    return False


def _has_completion_markers(session_output: str) -> bool:
    """Check if session output contains completion markers (case-insensitive).

    Uses pre-compiled regexes with word boundary matching to avoid false
    positives from substrings (e.g., 'abandoned' should not match 'done',
    'unsuccessful' should not match 'success').
    """
    for pattern in _COMPLETION_MARKER_REGEXES:
        if pattern.search(session_output):
            return True
    # Also check for commit hashes as completion signal
    if _COMMIT_HASH_RE.search(session_output):
        return True
    return False


def derive_session_outcome(
    exit_code: int,
    session_output: str,
    tool_calls_completed: int,
    duration_seconds: float,
) -> SessionOutcomeResult:
    """Derive session outcome from observable signals.

    This function is deterministic: same inputs always produce the same output.
    No network calls, no datetime.now(), no side effects.

    Args:
        exit_code: Process exit code (0 = clean exit).
        session_output: Captured session output text for marker detection.
        tool_calls_completed: Number of tool invocations that completed.
        duration_seconds: Session duration in seconds.

    Returns:
        SessionOutcomeResult with outcome classification and reasoning.
    """
    signals: list[str] = []

    # Gate 1: FAILED — exit_code != 0 or error markers present
    if exit_code != 0:
        signals.append(f"exit_code={exit_code}")
        return SessionOutcomeResult(
            outcome=OUTCOME_FAILED,
            reason=f"Non-zero exit code: {exit_code}",
            signals_used=tuple(signals),
        )

    has_errors = _has_error_markers(session_output)
    if has_errors:
        signals.append("error_markers_detected")
        return SessionOutcomeResult(
            outcome=OUTCOME_FAILED,
            reason="Error markers detected in session output",
            signals_used=tuple(signals),
        )

    # Gate 2: SUCCESS — tool calls completed AND completion markers present
    has_completion = _has_completion_markers(session_output)
    if tool_calls_completed > 0 and has_completion:
        signals.append(f"tool_calls={tool_calls_completed}")
        signals.append("completion_markers_detected")
        return SessionOutcomeResult(
            outcome=OUTCOME_SUCCESS,
            reason=f"Session completed with {tool_calls_completed} tool calls and completion markers",
            signals_used=tuple(signals),
        )

    # Gate 3: ABANDONED — no completion markers and short duration
    if not has_completion and duration_seconds < ABANDON_THRESHOLD_SECONDS:
        signals.append(f"duration={duration_seconds:.1f}s")
        signals.append("no_completion_markers")
        return SessionOutcomeResult(
            outcome=OUTCOME_ABANDONED,
            reason=f"Session ended after {duration_seconds:.1f}s without completion markers",
            signals_used=tuple(signals),
        )

    # Gate 4: UNKNOWN — insufficient signal
    if tool_calls_completed > 0:
        signals.append(f"tool_calls={tool_calls_completed}")
    if has_completion:
        signals.append("completion_markers_detected")
    signals.append(f"duration={duration_seconds:.1f}s")

    return SessionOutcomeResult(
        outcome=OUTCOME_UNKNOWN,
        reason="Insufficient signal to classify session outcome",
        signals_used=tuple(signals),
    )


__all__ = [
    # Constants
    "ABANDON_THRESHOLD_SECONDS",
    "COMPLETION_MARKER_PATTERNS",
    "ERROR_MARKER_REGEXES",
    "OUTCOME_ABANDONED",
    "OUTCOME_FAILED",
    "OUTCOME_SUCCESS",
    "OUTCOME_UNKNOWN",
    # Types
    "SessionOutcomeResult",
    # Functions
    "derive_session_outcome",
]
