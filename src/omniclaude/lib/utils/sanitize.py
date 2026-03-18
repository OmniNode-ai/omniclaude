# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Sanitization utilities for secure logging.

Provides helpers to strip control characters from user-controlled input before
it reaches log statements (preventing log injection) and to redact sensitive
values such as database DSNs containing passwords.

Fixes CodeQL alerts:
- CWE-117: Log injection (OMN-5413)
- CWE-312: Cleartext storage of sensitive information (OMN-5414)
"""

from __future__ import annotations

import re

# Control characters: everything in the ASCII range 0x00–0x1F plus DEL (0x7F),
# excluding the safe whitespace characters tab (0x09) and space (0x20).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

# Matches common DSN/connection-string password fields.
# Handles both URL-form (://user:pass@host) and keyword-form (password=xxx).
_DSN_URL_PASSWORD_RE = re.compile(
    r"(://[^:@/]*:)([^@/]+)(@)",
    re.IGNORECASE,
)
_DSN_KW_PASSWORD_RE = re.compile(
    r"(password\s*=\s*)(\S+)",
    re.IGNORECASE,
)
_REDACTED = "***"


def sanitize_log_input(value: str) -> str:
    """Strip ASCII control characters from a string before logging.

    Replaces each control character with a space so that the overall structure
    of the value is preserved while preventing log-injection attacks that use
    newlines or other control characters to forge log entries.

    Args:
        value: Arbitrary string that will be included in a log message.

    Returns:
        The input string with all ASCII control characters replaced by spaces.

    Example:
        >>> sanitize_log_input("OmniNode-ai/omniclaude\\nINFO fake-entry")
        'OmniNode-ai/omniclaude INFO fake-entry'
    """
    return _CONTROL_CHAR_RE.sub(" ", value)


def _redact_dsn(value: str) -> str:
    """Redact passwords from a database DSN or connection string.

    Handles both URL-form DSNs (``postgresql://user:pass@host/db``) and
    keyword-form DSNs (``host=... password=secret ...``).  All other parts of
    the value are left intact so that non-sensitive information (host, port,
    dbname) remains visible in logs.

    Args:
        value: A DSN or connection string that may contain a plaintext password.

    Returns:
        The DSN with any detected password component replaced by ``***``.

    Example:
        >>> _redact_dsn("postgresql://user:s3cr3t@localhost:5432/mydb")
        'postgresql://user:***@localhost:5432/mydb'
        >>> _redact_dsn("host=localhost password=s3cr3t dbname=mydb")
        'host=localhost password=*** dbname=mydb'
    """
    # URL-form: ://user:PASSWORD@host
    value = _DSN_URL_PASSWORD_RE.sub(rf"\g<1>{_REDACTED}\g<3>", value)
    # Keyword-form: password=PASSWORD
    value = _DSN_KW_PASSWORD_RE.sub(rf"\g<1>{_REDACTED}", value)
    return value


def redact_config_dict(config: dict[str, object]) -> dict[str, object]:
    """Return a copy of *config* with sensitive keys redacted.

    Keys whose names contain ``password``, ``secret``, ``token``, or ``key``
    (case-insensitive) have their values replaced with ``"***"``.  All other
    key/value pairs are returned unchanged.

    Args:
        config: A flat mapping of configuration key names to values.

    Returns:
        A new dict with sensitive values redacted.
    """
    _SENSITIVE = re.compile(r"password|secret|token|key", re.IGNORECASE)
    return {
        k: (_REDACTED if _SENSITIVE.search(k) else v) for k, v in config.items()
    }
