#!/usr/bin/env python3
"""Secret redaction for hook event payloads.

Uses re.search() (not match) for pattern detection to find secrets
anywhere in the text, not just at the start.

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Import secret patterns from schemas to avoid duplication
# The schemas module is the canonical source for secret patterns
try:
    from omniclaude.hooks.schemas import _SECRET_PATTERNS

    SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = _SECRET_PATTERNS
except ImportError:
    # Fallback if schemas not available (e.g., standalone usage)
    # This should not happen in normal operation
    import logging

    logging.getLogger(__name__).warning(
        "Could not import _SECRET_PATTERNS from schemas, using minimal fallback"
    )
    SECRET_PATTERNS = [
        (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
        (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "ghp_***REDACTED***"),
    ]


class RedactionResult(NamedTuple):
    """Result of secret redaction."""

    text: str
    redacted_count: int


def redact_secrets(text: str) -> str:
    """Redact secrets from text using search() pattern matching.

    Uses re.search() semantics to find secrets anywhere in text,
    not just at the start (unlike re.match()).

    Args:
        text: Text that may contain secrets.

    Returns:
        Text with secrets redacted.

    Example:
        >>> redact_secrets("My key is sk-1234567890abcdefghij")
        'My key is sk-***REDACTED***'
    """
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_secrets_with_count(text: str) -> RedactionResult:
    """Redact secrets and return count of redactions made.

    Args:
        text: Text that may contain secrets.

    Returns:
        RedactionResult with redacted text and count.

    Example:
        >>> result = redact_secrets_with_count("key=sk-1234567890abcdefghij12345 password=secretpass123")
        >>> result.redacted_count >= 2
        True
    """
    result = text
    redacted_count = 0

    for pattern, replacement in SECRET_PATTERNS:
        # Use subn() to replace and count in one pass
        result, count = pattern.subn(replacement, result)
        redacted_count += count

    return RedactionResult(text=result, redacted_count=redacted_count)


def contains_secrets(text: str) -> bool:
    """Check if text contains any detectable secrets.

    Uses search() to find secrets anywhere in text.

    Args:
        text: Text to check.

    Returns:
        True if any secret patterns are found.
    """
    for pattern, _ in SECRET_PATTERNS:
        if pattern.search(text):
            return True
    return False


__all__ = [
    "SECRET_PATTERNS",
    "RedactionResult",
    "redact_secrets",
    "redact_secrets_with_count",
    "contains_secrets",
]
