#!/usr/bin/env python3
"""Secret redaction for hook event payloads.

Uses re.search() (not match) for pattern detection to find secrets
anywhere in the text, not just at the start.

Part of OMN-1889: Emit injection metrics + utilization signal.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# =============================================================================
# Secret Patterns (compiled for performance)
# =============================================================================
# All patterns use search() semantics - they find secrets anywhere in text

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # OpenAI API keys
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
    # AWS Access Keys
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AKIA***REDACTED***"),
    # GitHub Personal Access Tokens
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "ghp_***REDACTED***"),
    # GitHub OAuth tokens
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "gho_***REDACTED***"),
    # Slack tokens (bot, app, user, etc.)
    (re.compile(r"xox[baprs]-[a-zA-Z0-9-]{10,}"), "xox*-***REDACTED***"),
    # Bearer tokens
    (
        re.compile(r"Bearer\s+[a-zA-Z0-9._-]{20,}", re.IGNORECASE),
        "Bearer ***REDACTED***",
    ),
    # PEM private keys
    (
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----"
        ),
        "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
    ),
    # Stripe API keys
    (
        re.compile(r"(?:sk|pk|rk)_(?:live|test)_[a-zA-Z0-9]{24,}"),
        "stripe_***REDACTED***",
    ),
    # Google Cloud API keys
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "AIza***REDACTED***"),
    # JWT tokens (three-part base64)
    (
        re.compile(r"eyJ[a-zA-Z0-9_-]*\.eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*"),
        "jwt_***REDACTED***",
    ),
    # Password in URLs
    (re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
    # Generic secrets (password=, secret=, token=, api_key=)
    (
        re.compile(
            r"(\b(?:password|passwd|secret|token|api_key|apikey|auth)\s*[=:]\s*)['\"]?[^\s'\"]{8,}['\"]?",
            re.IGNORECASE,
        ),
        r"\1***REDACTED***",
    ),
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
        # Use search to check if pattern exists anywhere in text
        if pattern.search(result):
            result = pattern.sub(replacement, result)
    return result


def redact_secrets_with_count(text: str) -> RedactionResult:
    """Redact secrets and return count of redactions made.

    Args:
        text: Text that may contain secrets.

    Returns:
        RedactionResult with redacted text and count.

    Example:
        >>> result = redact_secrets_with_count("key1=sk-abc123... key2=ghp_xyz...")
        >>> result.redacted_count
        2
    """
    result = text
    redacted_count = 0

    for pattern, replacement in SECRET_PATTERNS:
        # Count matches before replacement
        matches = pattern.findall(result)
        if matches:
            redacted_count += len(matches)
            result = pattern.sub(replacement, result)

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
