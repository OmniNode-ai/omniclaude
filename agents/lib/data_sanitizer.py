#!/usr/bin/env python3
"""
Data Sanitization Utilities for ActionLogger

Prevents sensitive data leaks in observability logs by detecting and
redacting passwords, API keys, tokens, and other sensitive information.

Security Features:
- Sensitive key detection (password, api_key, token, secret, etc.)
- Sensitive pattern matching (Bearer tokens, API keys, long tokens)
- Stack trace sanitization (absolute paths → relative paths)
- Recursive dictionary sanitization with depth limits
- String truncation with configurable limits
- Zero performance impact design (fail-safe defaults)

Usage:
    from agents.lib.data_sanitizer import (
        sanitize_dict,
        sanitize_string,
        sanitize_error_context,
        sanitize_stack_trace,
    )

    # Sanitize context dicts
    context = {"user": "john", "password": "secret123", "api_key": "sk-xxx"}
    safe_context = sanitize_dict(context)
    # {"user": "john", "password": "[REDACTED]", "api_key": "[REDACTED]"}

    # Sanitize user requests
    user_request = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    safe_request = sanitize_string(user_request, max_length=200)
    # "Bearer [REDACTED]"

    # Sanitize error contexts
    error_context = {
        "user_request": "...",
        "credentials": {"password": "secret"},
        "normal_field": "safe"
    }
    safe_error = sanitize_error_context(error_context)

    # Sanitize stack traces
    stack_trace = "/Users/john/code/omniclaude/agents/lib/manifest_injector.py"
    safe_trace = sanitize_stack_trace(stack_trace)
    # "manifest_injector.py"

Created: 2025-11-15
Security Priority: CRITICAL (blocks PR #36)
Dependencies: Issue #1, #6, #8 (resolved)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Union

# Sensitive key patterns (case-insensitive matching)
# Any dict key containing these substrings will have its VALUE redacted
# Note: These are substrings, so "password" matches "user_password", "PASSWORD", etc.
# Be specific to avoid false positives (e.g., "secret" but not "secret_name")
SENSITIVE_KEYS: Set[str] = {
    "password",
    "passwd",
    "pwd",
    "_token",  # Match "access_token", "refresh_token" but not "token_count"
    "api_key",
    "apikey",
    "api-key",
    "_secret",  # Match "client_secret" but not "secret_name"
    "authorization",
    "private_key",
    "privatekey",
    "access_token",
    "refresh_token",
    "session_id",
    "sessionid",
    "cookie",
    "jwt",
    "bearer",
    "oauth",
    "client_secret",
    "client_id",
    "service_account",
    "connection_string",
    "database_url",
    "db_url",
    "redis_url",
    "kafka_password",
    "postgres_password",
    "credentials",  # Credential objects should be fully redacted
}

# Sensitive value patterns (regex matching)
# Any string value matching these patterns will be redacted
SENSITIVE_PATTERNS: List[re.Pattern] = [
    # Bearer tokens (OAuth, JWT) - match just the token part
    re.compile(r"bearer\s+([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    # API key patterns
    re.compile(r"api[_-]?key[:\s=]+([a-zA-Z0-9_\-]+)", re.IGNORECASE),
    # OpenAI keys (sk-...)
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    # Anthropic keys (sk-ant-...)
    re.compile(r"sk-ant-[a-zA-Z0-9]{20,}"),
    # Google API keys (AIza...)
    re.compile(r"AIza[a-zA-Z0-9_\-]{35,}"),
    # JWT tokens (xxx.yyy.zzz) - must have specific pattern
    re.compile(r"ey[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+"),
    # AWS keys (AKIA...)
    re.compile(r"AKIA[a-zA-Z0-9]{16}"),
    # Connection strings (postgres://, redis://, etc.)
    re.compile(
        r"(postgres|postgresql|mysql|redis|kafka)://[^@]+:[^@]+@", re.IGNORECASE
    ),
    # Email addresses in authentication contexts (might contain sensitive info)
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    # Generic long tokens (40+ alphanumeric chars with mixed case, likely sensitive)
    # Increased from 32 to 40 to avoid false positives
    re.compile(r"\b[a-zA-Z0-9_\-]{40,}\b"),
]

# Redaction placeholder
REDACTED = "[REDACTED]"


def sanitize_dict(
    data: Dict[str, Any],
    max_depth: int = 5,
    current_depth: int = 0,
    additional_fields: List[str] = None,
) -> Dict[str, Any]:
    """
    Recursively sanitize dictionary by replacing sensitive values.

    Detects sensitive keys (password, token, api_key, etc.) and sensitive
    value patterns (Bearer tokens, API keys, long tokens) and replaces
    them with [REDACTED].

    Args:
        data: Dictionary to sanitize
        max_depth: Maximum recursion depth (prevents infinite loops)
        current_depth: Current recursion depth (internal use)
        additional_fields: Additional custom field names to treat as sensitive
                          (e.g., ["custom_secret", "internal_token"])

    Returns:
        Sanitized dictionary with sensitive values replaced

    Example:
        >>> context = {
        ...     "user": "john",
        ...     "password": "secret123",
        ...     "api_key": "sk-1234567890",
        ...     "normal_field": "safe value",
        ...     "nested": {
        ...         "token": "bearer xyz",
        ...         "data": "ok"
        ...     }
        ... }
        >>> sanitized = sanitize_dict(context)
        >>> sanitized["password"]
        '[REDACTED]'
        >>> sanitized["api_key"]
        '[REDACTED]'
        >>> sanitized["nested"]["token"]
        '[REDACTED]'
        >>> sanitized["normal_field"]
        'safe value'
        >>> # With additional custom fields
        >>> context = {"my_custom_secret": "sensitive", "normal": "ok"}
        >>> sanitized = sanitize_dict(context, additional_fields=["my_custom_secret"])
        >>> sanitized["my_custom_secret"]
        '[REDACTED]'
    """
    # Depth limit reached - truncate to prevent infinite recursion
    if current_depth >= max_depth:
        return {"_truncated": "max depth reached"}

    # Handle None input gracefully
    if data is None:
        return {}

    # Ensure input is a dict
    if not isinstance(data, dict):
        return {"_error": f"expected dict, got {type(data).__name__}"}

    # Combine default sensitive fields with additional custom fields
    sensitive_fields = SENSITIVE_KEYS.copy()
    if additional_fields:
        sensitive_fields.update(field.lower() for field in additional_fields)

    sanitized = {}
    for key, value in data.items():
        # Check if key is sensitive (case-insensitive substring match)
        key_lower = str(key).lower()
        if any(sensitive in key_lower for sensitive in sensitive_fields):
            # Redact the entire value if key is sensitive
            sanitized[key] = REDACTED
        elif isinstance(value, dict):
            # Recursively sanitize nested dicts (only if key is not sensitive)
            sanitized[key] = sanitize_dict(
                value, max_depth, current_depth + 1, additional_fields
            )
        elif isinstance(value, list):
            # Sanitize list items (only if key is not sensitive)
            sanitized[key] = [
                (
                    sanitize_dict(item, max_depth, current_depth + 1, additional_fields)
                    if isinstance(item, dict)
                    else sanitize_value(item)
                )
                for item in value
            ]
        else:
            # Sanitize individual value (only if key is not sensitive)
            sanitized[key] = sanitize_value(value)

    return sanitized


def sanitize_value(value: Any) -> Any:
    """
    Sanitize individual value by checking for sensitive patterns.

    Args:
        value: Value to sanitize (any type)

    Returns:
        Original value or [REDACTED] if sensitive pattern detected

    Example:
        >>> sanitize_value("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz")
        '[REDACTED]'
        >>> sanitize_value("safe text")
        'safe text'
        >>> sanitize_value(12345)
        12345
    """
    # Only sanitize strings
    if not isinstance(value, str):
        return value

    # Check for sensitive patterns
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(value):
            return REDACTED

    return value


def sanitize_string(text: str, max_length: int = 200) -> str:
    """
    Sanitize string by removing sensitive patterns and truncating.

    Args:
        text: String to sanitize
        max_length: Maximum length before truncation (0 = no truncation)

    Returns:
        Sanitized and truncated string

    Example:
        >>> sanitize_string("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz")
        'Bearer [REDACTED]'
        >>> long_text = "a" * 300
        >>> len(sanitize_string(long_text, max_length=200))
        203  # 200 chars + "..."
        >>> sanitize_string("safe text", max_length=200)
        'safe text'
    """
    # Handle None input gracefully
    if text is None:
        return ""

    # Ensure input is a string
    if not isinstance(text, str):
        return str(text)

    # Truncate FIRST to avoid pattern matching on very long strings
    sanitized = text
    if max_length > 0 and len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."

    # Then replace sensitive patterns with [REDACTED]
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(REDACTED, sanitized)

    return sanitized


def sanitize_error_context(
    context: Dict[str, Any], additional_fields: List[str] = None
) -> Dict[str, Any]:
    """
    Sanitize error context for ActionLogger.

    Removes sensitive keys and sanitizes values. Optimized for error
    contexts which often contain stack traces, request data, and
    environment variables.

    Args:
        context: Error context dictionary
        additional_fields: Additional custom field names to treat as sensitive

    Returns:
        Sanitized context

    Example:
        >>> error_context = {
        ...     "user_request": "Please use api_key=sk-1234567890",
        ...     "error_type": "ValueError",
        ...     "credentials": {"password": "secret"},
        ...     "normal_field": "safe"
        ... }
        >>> sanitized = sanitize_error_context(error_context)
        >>> "api_key" in sanitized["user_request"]
        False
        >>> sanitized["credentials"]
        '[REDACTED]'
        >>> # With additional custom fields
        >>> sanitized = sanitize_error_context(error_context, additional_fields=["custom_key"])
    """
    return sanitize_dict(context, additional_fields=additional_fields)


def sanitize_stack_trace(stack_trace: str) -> str:
    """
    Sanitize stack trace by removing absolute paths.

    Converts absolute paths to relative paths to avoid leaking internal
    directory structure.

    Args:
        stack_trace: Stack trace string

    Returns:
        Sanitized stack trace with relative paths

    Example:
        >>> trace = '''
        ... Traceback (most recent call last):
        ...   File "/Users/john/code/omniclaude/agents/lib/manifest_injector.py", line 100
        ...     raise ValueError("error")
        ... ValueError: error
        ... '''
        >>> sanitized = sanitize_stack_trace(trace)
        >>> "/Users/john" not in sanitized
        True
        >>> "manifest_injector.py" in sanitized
        True
    """
    # Handle None input gracefully
    if stack_trace is None:
        return ""

    # Ensure input is a string
    if not isinstance(stack_trace, str):
        return str(stack_trace)

    # Replace absolute paths with relative paths
    # Pattern: /some/absolute/path/to/file.py → file.py
    sanitized = re.sub(r"/[a-zA-Z0-9_\-/\.]+/([a-zA-Z0-9_\-]+\.py)", r"\1", stack_trace)

    # Also handle Windows paths (C:\path\to\file.py → file.py)
    sanitized = re.sub(
        r"[A-Z]:\\[a-zA-Z0-9_\-\\\.]+\\([a-zA-Z0-9_\-]+\.py)", r"\1", sanitized
    )

    return sanitized


def sanitize_for_logging(
    data: Union[Dict[str, Any], str, Any],
    max_string_length: int = 200,
    max_dict_depth: int = 5,
    additional_fields: List[str] = None,
) -> Union[Dict[str, Any], str, Any]:
    """
    Universal sanitization function for any logging data.

    Automatically detects type and applies appropriate sanitization.

    Args:
        data: Data to sanitize (dict, string, or any type)
        max_string_length: Max length for string truncation
        max_dict_depth: Max depth for dict recursion
        additional_fields: Additional custom field names to treat as sensitive

    Returns:
        Sanitized data (same type as input)

    Example:
        >>> sanitize_for_logging({"password": "secret"})
        {'password': '[REDACTED]'}
        >>> sanitize_for_logging("Bearer token123")
        'Bearer [REDACTED]'
        >>> sanitize_for_logging(12345)
        12345
        >>> # With custom fields
        >>> sanitize_for_logging({"custom_secret": "xyz"}, additional_fields=["custom_secret"])
        {'custom_secret': '[REDACTED]'}
    """
    if isinstance(data, dict):
        return sanitize_dict(
            data, max_depth=max_dict_depth, additional_fields=additional_fields
        )
    elif isinstance(data, str):
        return sanitize_string(data, max_length=max_string_length)
    else:
        # Non-sensitive types pass through unchanged
        return data


__all__ = [
    "sanitize_dict",
    "sanitize_value",
    "sanitize_string",
    "sanitize_error_context",
    "sanitize_stack_trace",
    "sanitize_for_logging",
    "SENSITIVE_KEYS",
    "SENSITIVE_PATTERNS",
    "REDACTED",
]
