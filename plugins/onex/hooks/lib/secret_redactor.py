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
    # This should not happen in normal operation.
    # These patterns mirror _SECRET_PATTERNS in schemas.py — keep in sync.
    import logging

    SECRET_PATTERNS = [
        # OpenAI API keys
        (re.compile(r"\bsk-[a-zA-Z0-9]{20,}", re.IGNORECASE), "sk-***REDACTED***"),
        # AWS Access Keys
        (re.compile(r"\bAKIA[A-Z0-9]{16}", re.IGNORECASE), "AKIA***REDACTED***"),
        # GitHub tokens (personal access, OAuth)
        (re.compile(r"\bghp_[a-zA-Z0-9]{36}", re.IGNORECASE), "ghp_***REDACTED***"),
        (re.compile(r"\bgho_[a-zA-Z0-9]{36}", re.IGNORECASE), "gho_***REDACTED***"),
        # Slack tokens
        (
            re.compile(r"\bxox[baprs]-[a-zA-Z0-9-]{10,}", re.IGNORECASE),
            "xox*-***REDACTED***",
        ),
        # Stripe API keys (publishable, secret, and restricted)
        (
            re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[a-zA-Z0-9]{24,}", re.IGNORECASE),
            "stripe_***REDACTED***",
        ),
        # Google Cloud Platform API keys
        (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}"), "AIza***REDACTED***"),
        # JWT tokens
        (
            re.compile(r"\beyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*"),
            "jwt_***REDACTED***",
        ),
        # Private keys (PEM format)
        (
            re.compile(
                r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
            ),
            "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
        ),
        # Bearer tokens
        (
            re.compile(r"(Bearer\s+)[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        # Password in URLs
        (re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
        # Generic secret patterns in key=value format
        (
            re.compile(
                r"(\b(?:password|passwd|secret|token|api_key|apikey|auth)\s*[=:]\s*)['\"]?[^\s'\"]{8,}['\"]?",
                re.IGNORECASE,
            ),
            r"\1***REDACTED***",
        ),
    ]

    logging.getLogger(__name__).warning(
        "Could not import _SECRET_PATTERNS from schemas, using standalone fallback "
        f"({len(SECRET_PATTERNS)} patterns)"
    )


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

    Uses subn() for accurate counting. Note: Some patterns have capturing groups
    for backreference replacements (e.g., "Bearer " prefix preservation). Using
    subn() is correct here because it counts SUBSTITUTIONS, not matches.

    DO NOT use findall() with SECRET_PATTERNS - capturing groups would cause
    findall() to return only the captured portions, not full matches.

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
        # subn() returns (new_string, number_of_substitutions_made)
        # This count is accurate regardless of capturing groups in the pattern
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
