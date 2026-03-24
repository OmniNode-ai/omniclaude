#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared sanitization for injection pattern detection and field neutralization.

Provides two complementary sanitization modes:

1. **check_field_injection(value, field_name)** -- Reject mode.
   Used for structured YAML validation (linear_contract_patcher.py).
   Returns an error string if a prohibited pattern is detected, None if clean.
   Fails closed: any match is a hard rejection.

2. **sanitize_field(value)** -- Neutralize mode.
   Used for rendering/display paths (ticket_context_injector.py).
   Strips or neutralizes prohibited patterns in-place. Always returns a string.
   Fails safe: residual unsafe content is defanged, never propagated verbatim.

Policy:
    Pattern-based denylist v1. Conservative. This is NOT a general prompt
    injection solution -- it targets the specific injection vectors identified
    in the OMN-6366 security review (trust boundary markers, context headers,
    instruction override attempts).

[OMN-6372]
"""

from __future__ import annotations

import re

# =============================================================================
# Injection Pattern Denylist
# =============================================================================

# Each entry is (compiled_regex, human_description).
# Patterns are checked case-insensitively.
INJECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Trust boundary marker forgery
    (
        re.compile(r"</?omniclaude-context[^>]*>", re.IGNORECASE),
        "omniclaude-context XML tag (trust boundary marker forgery)",
    ),
    # Section header spoofing (5+ equals signs used as visual separators)
    (
        re.compile(r"={5,}"),
        "long equals-sign separator (section header spoofing)",
    ),
    # Context/routing/override header injection
    (
        re.compile(
            r"##\s+(?:AGENT|SYSTEM|HOOK)\s+(?:CONTEXT|ROUTING|OVERRIDE)",
            re.IGNORECASE,
        ),
        "agent/system/hook context header injection",
    ),
    # Instruction override attempts
    (
        re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
        "instruction override attempt",
    ),
    # System prompt injection via markdown
    (
        re.compile(
            r"<system>|</system>|<system-prompt>|</system-prompt>", re.IGNORECASE
        ),
        "system prompt XML tag injection",
    ),
]


# =============================================================================
# Reject Mode (for structured YAML validation)
# =============================================================================


def check_field_injection(value: str, field_name: str) -> str | None:
    """Check a field value for injection patterns. Reject mode.

    Used by linear_contract_patcher.py for structured YAML validation.
    Any match is a hard rejection -- the entire contract update should be
    refused when this returns non-None.

    Args:
        value: The field value to check.
        field_name: Name of the field being checked (for error messages).

    Returns:
        Error string describing the injection detected, or None if clean.
    """
    if not isinstance(value, str):
        return None

    for pattern, description in INJECTION_PATTERNS:
        match = pattern.search(value)
        if match:
            return (
                f"Injection detected in field '{field_name}': "
                f"{description} (matched: {match.group()!r})"
            )

    return None


# =============================================================================
# Neutralize Mode (for rendering/display paths)
# =============================================================================


def sanitize_field(value: str) -> str:
    """Neutralize injection patterns in a field value. Rendering mode.

    Used by ticket_context_injector.py for display paths where content
    must be shown but injection patterns must be defanged.

    Strips or replaces prohibited patterns:
    - XML-like tags are removed entirely
    - Long equals-sign separators are truncated to 3 chars
    - Header injections have ## prefix removed
    - Instruction overrides are replaced with [REDACTED]

    Args:
        value: The field value to sanitize.

    Returns:
        Sanitized string. Always returns a string (never None).
    """
    if not isinstance(value, str):
        return str(value) if value is not None else ""

    result = value

    # Remove trust boundary marker blocks (tags + content between them).
    # Forged trust blocks must be removed entirely -- not just the tags --
    # to prevent content within a forged trust="system" block from leaking.
    result = re.sub(
        r"<omniclaude-context[^>]*>.*?</omniclaude-context>",
        "",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Also strip orphaned tags (opening without closing, or vice versa)
    result = re.sub(r"</?omniclaude-context[^>]*>", "", result, flags=re.IGNORECASE)

    # Remove system prompt blocks (tags + content) and orphaned tags
    result = re.sub(
        r"<(?:system|system-prompt)>.*?</(?:system|system-prompt)>",
        "",
        result,
        flags=re.IGNORECASE | re.DOTALL,
    )
    result = re.sub(r"</?(?:system|system-prompt)>", "", result, flags=re.IGNORECASE)

    # Truncate long equals-sign separators to 3 chars
    result = re.sub(r"={5,}", "===", result)

    # Remove ## prefix from context/routing/override headers
    result = re.sub(
        r"##\s+(?:AGENT|SYSTEM|HOOK)\s+(?:CONTEXT|ROUTING|OVERRIDE)",
        "[REDACTED HEADER]",
        result,
        flags=re.IGNORECASE,
    )

    # Replace instruction overrides
    result = re.sub(
        r"ignore\s+previous\s+instructions",
        "[REDACTED]",
        result,
        flags=re.IGNORECASE,
    )

    return result
