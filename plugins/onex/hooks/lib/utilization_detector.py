#!/usr/bin/env python3
"""Utilization detection for context injection effectiveness.

Measures whether injected context was actually used by comparing identifiers
between injected patterns and Claude's response.

Performance requirement: 30ms soft timeout budget with graceful degradation.

**Timeout Design (Cooperative with Granular Checks)**:
This module uses a cooperative timeout model with per-pattern checking.
The timeout_ms parameter is a "soft budget" - we check elapsed time AFTER
each regex pattern completes (5 patterns per extraction), not during. This means:

- Timeout is checked after EACH of the 5 regex patterns (not just after extraction)
- A single slow regex pattern can still exceed budget before its check
- Input size limits (MAX_INPUT_SIZE) prevent pathological cases
- This is intentional: Python regex cannot be safely interrupted mid-execution

Why not hard timeouts?
1. Python regex operations are atomic C extensions - cannot be interrupted
2. signal.alarm() only supports whole-second granularity (we need 30ms)
3. Threading adds complexity and potential race conditions for minimal gain
4. Regex on typical inputs completes in <5ms, so post-check is sufficient

Defense in depth:
1. Input size limits (MAX_INPUT_SIZE = ~50K chars) prevent pathological cases
2. Per-pattern timeout checks (5 checks per extraction, 10+ total)
3. Graceful degradation with score=0.0 on timeout

Graceful degradation: If timeout is exceeded, returns timeout_fallback result
with score=0.0. If timeout exceeds 2x budget, a warning is logged.

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import sys
import time
from typing import NamedTuple

# =============================================================================
# Regex Patterns (non-capturing groups for performance)
# =============================================================================

# CamelCase or snake_case identifiers (min 3 chars to avoid noise)
IDENTIFIER_RE = re.compile(r"(?:[A-Z][a-z]+){2,}|[a-z_][a-z0-9_]{2,}")

# File paths (Unix or relative)
PATH_RE = re.compile(r"(?:/[\w.-]+)+|(?:[\w.-]+/)+[\w.-]+")

# Ticket IDs (OMN-123, FEAT-456, BUG-789)
TICKET_RE = re.compile(r"(?:OMN|FEAT|BUG|TASK|ISSUE)-\d+", re.IGNORECASE)

# URLs (http/https)
URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Environment variable keys (UPPER_SNAKE_CASE)
ENV_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")

# All patterns in order of application (for timeout checking)
_ALL_PATTERNS = [IDENTIFIER_RE, PATH_RE, TICKET_RE, URL_RE, ENV_KEY_RE]

# =============================================================================
# Input Size Limits (Defense in Depth)
# =============================================================================

# Maximum input size in characters (~50K chars). Inputs larger than this are
# truncated to prevent pathological regex performance. This is a defense-in-depth
# measure alongside per-pattern timeout checking.
# Note: This is character count (len(text)), not byte count. For UTF-8 text with
# multi-byte characters, actual byte size may differ.
MAX_INPUT_SIZE = 50 * 1024  # ~50K characters

# =============================================================================
# Stopwords (English + Python keywords to prevent score inflation)
# =============================================================================
# NOTE: All stopwords are lowercase to match identifier normalization.
# Identifiers are normalized via .lower() before comparison
# (in _extract_identifiers_with_timeout). This ensures case-insensitive
# stopword filtering.

ENGLISH_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "from",
        "have",
        "has",
        "was",
        "were",
        "will",
        "would",
        "could",
        "should",
        "been",
        "being",
        "are",
        "not",
        "but",
        "what",
        "when",
        "where",
        "which",
        "who",
        "how",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "than",
        "too",
        "very",
        "can",
        "just",
        "now",
        "use",
        "used",
        "using",
        "also",
        "into",
        "only",
        "over",
        "after",
        "before",
        "between",
        "through",
        "during",
        "without",
    }
)

CODE_STOPWORDS = frozenset(
    {
        # Python keywords (lowercase for comparison after normalization)
        "def",
        "class",
        "return",
        "import",
        "from",
        "none",
        "true",
        "false",
        "self",
        "cls",
        "async",
        "await",
        "yield",
        "lambda",
        "pass",
        "break",
        "continue",
        "raise",
        "try",
        "except",
        "finally",
        "with",
        "assert",
        "global",
        "nonlocal",
        "del",
        "elif",
        "else",
        # Common primitives/types (lowercase for comparison)
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "bytes",
        "type",
        "object",
        "any",
        "optional",
        "union",
        # Common variable names
        "args",
        "kwargs",
        "result",
        "value",
        "data",
        "item",
        "items",
        "name",
        "key",
        "keys",
        "index",
        "count",
        "length",
        "size",
    }
)

# Explicit normalization ensures case-insensitive comparison even if
# someone accidentally adds a mixed-case stopword to the source sets.
ALL_STOPWORDS = frozenset(word.lower() for word in ENGLISH_STOPWORDS | CODE_STOPWORDS)


# =============================================================================
# Timeout Handling
# =============================================================================


class UtilizationTimeoutError(Exception):
    """Raised when utilization detection exceeds timeout."""

    pass


# =============================================================================
# Guaranteed-Visibility Logging
# =============================================================================


def _log_with_guaranteed_visibility(message: str, level: str = "WARNING") -> None:
    """Log a message with guaranteed visibility.

    Ensures messages are visible by:
    1. Always writing to stderr (visible in hook output)
    2. Writing to LOG_FILE if configured (respects hook system config)
    3. Using standard logging (for log aggregation)

    This is critical for failure diagnostics in hook contexts where
    standard logging may not be configured or visible.

    Args:
        message: The message to log.
        level: Log level string (WARNING, ERROR, etc).
    """
    # Format with timestamp and level for consistency
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    formatted = f"[{timestamp}] {level}: {message}"

    # 1. Always write to stderr (guaranteed visible in hooks)
    print(formatted, file=sys.stderr)

    # 2. Write to LOG_FILE if configured (hook system config)
    log_file = os.environ.get("LOG_FILE")
    if log_file:
        try:
            with open(log_file, "a") as f:
                f.write(formatted + "\n")
        except OSError:
            # Cannot write to log file - stderr already has the message
            pass

    # 3. Also use standard logging for aggregation systems
    logger = logging.getLogger(__name__)
    log_method = getattr(logger, level.lower(), logger.warning)
    log_method(message)


# =============================================================================
# Result Types
# =============================================================================


class UtilizationResult(NamedTuple):
    """Result of utilization detection."""

    score: float  # 0.0-1.0 ratio of reused identifiers
    method: str  # "identifier_overlap", "timeout_fallback", or "error_fallback"
    injected_count: int  # identifiers in injected context
    reused_count: int  # identifiers found in response
    duration_ms: int  # time taken for detection


# =============================================================================
# Identifier Extraction
# =============================================================================


def _extract_identifiers_with_timeout(
    text: str,
    start_time: float | None = None,
    timeout_ms: int | None = None,
) -> set[str]:
    """Extract identifiers with per-pattern timeout checking.

    Internal function that supports granular timeout enforcement by checking
    elapsed time after each regex pattern completes.

    Args:
        text: Text to extract identifiers from.
        start_time: Start time from time.perf_counter(). If None, no timeout checking.
        timeout_ms: Timeout budget in milliseconds. If None, no timeout checking.

    Returns:
        Set of unique identifiers (lowercase normalized).

    Raises:
        UtilizationTimeoutError: If timeout_ms exceeded after any pattern.
    """
    identifiers: set[str] = set()

    # Apply input size limit as defense in depth
    if len(text) > MAX_INPUT_SIZE:
        text = text[:MAX_INPUT_SIZE]

    # Extract from each pattern with timeout check after each
    for pattern in _ALL_PATTERNS:
        for match in pattern.findall(text):
            # Normalize to lowercase
            normalized = match.lower()
            # Filter stopwords
            if normalized not in ALL_STOPWORDS and len(normalized) >= 3:
                identifiers.add(normalized)

        # Per-pattern timeout check (granular enforcement)
        if start_time is not None and timeout_ms is not None:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > timeout_ms:
                raise UtilizationTimeoutError(
                    f"Exceeded {timeout_ms}ms timeout after pattern"
                )

    return identifiers


def extract_identifiers(text: str) -> set[str]:
    """Extract meaningful identifiers from text.

    Extracts:
    - CamelCase identifiers (ModelUserPayload)
    - snake_case identifiers (user_payload)
    - File paths (/src/models/user.py)
    - Ticket IDs (OMN-1889)
    - URLs
    - Environment keys (KAFKA_BOOTSTRAP_SERVERS)

    Filters out stopwords to prevent score inflation.

    Note:
        This is the public API without timeout support. For timeout-aware
        extraction, use calculate_utilization() which handles timeouts
        internally with per-pattern granularity.

    Args:
        text: Text to extract identifiers from.

    Returns:
        Set of unique identifiers (lowercase normalized).
    """
    return _extract_identifiers_with_timeout(text)


def calculate_utilization(
    injected_context: str,
    response_text: str,
    timeout_ms: int = 30,
) -> UtilizationResult:
    """Calculate utilization score by comparing identifiers.

    Compares identifiers from injected context against those in Claude's
    response to measure how much of the injected context was actually used.

    Args:
        injected_context: The context that was injected (patterns, etc).
        response_text: Claude's response text.
        timeout_ms: Soft timeout budget in milliseconds (default: 30ms).
            Timeout is checked after EACH of the 5 regex patterns (per-pattern
            granularity), not just after entire extraction. This provides ~10
            timeout checkpoints total. See module docstring for rationale.

    Returns:
        UtilizationResult with score, method, and counts.

    Note:
        - Input size is limited to MAX_INPUT_SIZE (~50K chars) as defense in depth
        - Timeout is checked after each of 5 regex patterns (10+ checkpoints)
        - If timeout exceeds 2x budget, an error is logged for investigation

    Example:
        >>> result = calculate_utilization(
        ...     "Use ModelUserPayload for /api/users endpoint",
        ...     "I'll use ModelUserPayload to handle the request"
        ... )
        >>> result.score > 0
        True
    """
    start_time = time.perf_counter()

    try:
        # Extract identifiers with per-pattern timeout checking
        # This checks timeout after EACH of 5 patterns (granular enforcement)
        injected_ids = _extract_identifiers_with_timeout(
            injected_context, start_time, timeout_ms
        )

        # Extract identifiers from response (continues from same start_time)
        response_ids = _extract_identifiers_with_timeout(
            response_text, start_time, timeout_ms
        )

        # Calculate overlap
        reused_ids = injected_ids & response_ids

        # Calculate score (avoid division by zero)
        injected_count = len(injected_ids)
        reused_count = len(reused_ids)

        if injected_count == 0:
            score = 0.0
        else:
            score = reused_count / injected_count

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return UtilizationResult(
            score=score,
            method="identifier_overlap",
            injected_count=injected_count,
            reused_count=reused_count,
            duration_ms=duration_ms,
        )

    except UtilizationTimeoutError:
        # Expected: timeout exceeded, graceful degradation
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Log ALL timeouts with guaranteed visibility for observability
        # Severity depends on how much we exceeded the budget:
        # - 1x-2x budget: WARNING (expected degradation under load)
        # - 2x+ budget: ERROR (unexpected, needs investigation)
        if duration_ms > timeout_ms * 2:
            _log_with_guaranteed_visibility(
                f"Utilization detection exceeded 2x timeout budget: "
                f"{duration_ms}ms (budget: {timeout_ms}ms). "
                f"Consider investigating input size or regex performance.",
                level="ERROR",
            )
        else:
            _log_with_guaranteed_visibility(
                f"Utilization detection timed out: {duration_ms}ms "
                f"(budget: {timeout_ms}ms). Returning fallback result.",
                level="WARNING",
            )

        return UtilizationResult(
            score=0.0,
            method="timeout_fallback",
            injected_count=0,
            reused_count=0,
            duration_ms=duration_ms,
        )
    except (ValueError, TypeError, AttributeError) as e:
        # Recoverable errors from malformed input - degrade gracefully
        # Use ERROR level: these are unexpected issues, not expected degradation
        # Use guaranteed-visibility logging for hook diagnostics
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        _log_with_guaranteed_visibility(
            f"Utilization detection failed with recoverable error: {e}",
            level="ERROR",
        )
        return UtilizationResult(
            score=0.0,
            method="error_fallback",  # Distinguish from timeout for accurate analytics
            injected_count=0,
            reused_count=0,
            duration_ms=duration_ms,
        )


__all__ = [
    # Patterns
    "IDENTIFIER_RE",
    "PATH_RE",
    "TICKET_RE",
    "URL_RE",
    "ENV_KEY_RE",
    # Limits
    "MAX_INPUT_SIZE",
    # Stopwords
    "ENGLISH_STOPWORDS",
    "CODE_STOPWORDS",
    "ALL_STOPWORDS",
    # Functions
    "extract_identifiers",
    "calculate_utilization",
    # Types
    "UtilizationResult",
    "UtilizationTimeoutError",
]
