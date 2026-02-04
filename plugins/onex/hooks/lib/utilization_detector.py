#!/usr/bin/env python3
"""Utilization detection for context injection effectiveness.

Measures whether injected context was actually used by comparing identifiers
between injected patterns and Claude's response.

Performance requirement: 30ms hard timeout with graceful degradation.

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import logging
import re
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

# =============================================================================
# Stopwords (English + Python keywords to prevent score inflation)
# =============================================================================
# NOTE: All stopwords are lowercase to match identifier normalization.
# Identifiers are normalized via .lower() before comparison (see line ~225).
# This ensures case-insensitive stopword filtering.

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

ALL_STOPWORDS = ENGLISH_STOPWORDS | CODE_STOPWORDS


# =============================================================================
# Timeout Handling
# =============================================================================


class UtilizationTimeoutError(Exception):
    """Raised when utilization detection exceeds timeout."""

    pass


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

    Args:
        text: Text to extract identifiers from.

    Returns:
        Set of unique identifiers (lowercase normalized).
    """
    identifiers: set[str] = set()

    # Extract from each pattern
    for pattern in [IDENTIFIER_RE, PATH_RE, TICKET_RE, URL_RE, ENV_KEY_RE]:
        for match in pattern.findall(text):
            # Normalize to lowercase
            normalized = match.lower()
            # Filter stopwords
            if normalized not in ALL_STOPWORDS and len(normalized) >= 3:
                identifiers.add(normalized)

    return identifiers


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
        timeout_ms: Hard timeout in milliseconds (default: 30ms).

    Returns:
        UtilizationResult with score, method, and counts.

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
        # Cooperative timeout design: We check elapsed time AFTER each operation
        # rather than using preemptive interruption (threads/signals) because:
        # 1. Python regex operations are atomic - cannot be interrupted mid-execution
        # 2. signal.alarm() only supports whole-second granularity (we need 30ms)
        # 3. Threading adds complexity and potential race conditions
        # 4. Regex on typical inputs completes in <5ms, so post-check is sufficient
        # If a single regex takes >30ms, we'll exceed timeout but still complete
        # gracefully - this is acceptable for the 30ms soft budget.

        # Extract identifiers from injected context
        injected_ids = extract_identifiers(injected_context)

        # Check manual timeout
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if elapsed_ms > timeout_ms:
            raise UtilizationTimeoutError(f"Exceeded {timeout_ms}ms timeout")

        # Extract identifiers from response
        response_ids = extract_identifiers(response_text)

        # Check manual timeout
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        if elapsed_ms > timeout_ms:
            raise UtilizationTimeoutError(f"Exceeded {timeout_ms}ms timeout")

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
        return UtilizationResult(
            score=0.0,
            method="timeout_fallback",
            injected_count=0,
            reused_count=0,
            duration_ms=duration_ms,
        )
    except (ValueError, TypeError, AttributeError) as e:
        # Recoverable errors from malformed input - degrade gracefully
        # Log at warning level for visibility in production diagnostics
        logging.getLogger(__name__).warning(
            f"Utilization detection failed with recoverable error: {e}"
        )
        duration_ms = int((time.perf_counter() - start_time) * 1000)
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
